"""Cancellation and voluntary demolition; retain history and protect stored assets."""
import copy
import json
from game.buildings import spec
from game.settlement import read_state

MATERIALS=('scrap','metal','electronics')


def refund(state, job):
    rules=state['config']['maintenance']
    progress=min(1,job['work_completed']/job['work_required'])
    fraction=rules['cancel_refund_start']+(rules['cancel_refund_end']-rules['cancel_refund_start'])*progress
    spent=json.loads(job['inputs_spent'])
    return {r:spent.get(r,0)*fraction for r in MATERIALS}


def recovery(state, building):
    jobs=[j for j in state['jobs'] if j['target_building_id']==building['building_id'] and j['job_type'] in ('construction','upgrade') and j['status']=='completed']
    # Older/pre-seeded structures may have no funded construction history.
    invested={r:sum(json.loads(j['inputs_spent']).get(r,0) for j in jobs) if jobs else sum(s[r] for s in state['config']['buildings'][building['building_type']]['levels'][:building['level']]) for r in MATERIALS}
    return {r:invested[r]*state['config']['maintenance']['demolition_recovery'][r] for r in MATERIALS}


def credit(connection,state,amounts,now):
    """Incoming recovery uses free shared storage; proportional overflow is discarded."""
    from game.economy import storage
    free=max(0,storage(state)['material']-sum(state['resources'][r] for r in MATERIALS))
    total=sum(amounts.values());factor=min(1,free/total) if total else 1
    delivered={r:amounts[r]*factor for r in MATERIALS}
    connection.execute('UPDATE settlement_resources SET scrap=scrap+?,metal=metal+?,electronics=electronics+?,updated_at=? WHERE settlement_id=?',(*delivered.values(),now,state['settlement']['settlement_id']))
    return delivered


def command(connection,state,action,bid,now):
    if 'maintenance' not in state['config']:raise ValueError('Enable maintenance and building management first.')
    b=next((b for b in state['buildings'] if b['building_id']==bid),None)
    if not b:raise ValueError('Choose your own building.')
    if b['status'] in ('demolished','cleared'):return
    active=[j for j in state['jobs'] if j['target_building_id']==bid and j['status'] in ('queued','active','paused')]
    if action=='cancel_build':
        job=next((j for j in active if j['job_type'] in ('construction','upgrade')),None)
        if not job:raise ValueError('Choose an unfinished construction or upgrade project.')
        amounts=refund(state,job)
        connection.execute("UPDATE settlement_jobs SET status='cancelled',pause_reason='Cancelled by player',last_processed_at=? WHERE job_id=?",(now,job['job_id']))
        connection.execute("UPDATE citizens SET unemployed_since=? WHERE citizen_id IN (SELECT citizen_id FROM citizen_assignments WHERE job_id=? AND ended_at IS NULL)",(now,job['job_id']))
        connection.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='project_cancelled' WHERE job_id=? AND ended_at IS NULL",(now,job['job_id']))
        if job['job_type']=='upgrade':connection.execute("UPDATE buildings SET status='active' WHERE building_id=?",(bid,))
        else:connection.execute("UPDATE buildings SET status='demolished',current_hp=0,cleared_at=? WHERE building_id=?",(now,bid))
    else:
        if b['building_type']=='town_hall':raise ValueError('The Town Hall cannot be demolished.')
        if b['status']!='active' or b['current_hp']<=0 or active:raise ValueError('Finish or cancel this building’s projects before demolition.')
        from game.manufacturing import occupancy
        if occupancy(state,bid):raise ValueError('This building still stores military assets or a funded unit. It cannot be demolished.')
        if any(j['production_building_id']==bid and j['status'] in ('queued','active','paused') for j in state['jobs']):raise ValueError('Finish or cancel this factory’s batches first.')
        if any(j['production_building_id']==bid and j['job_type']=='drone_repair' and j['status'] in ('active','paused') for j in state['jobs']):raise ValueError('Finish drone maintenance first.')
        proposed=copy.deepcopy(state)
        next(x for x in proposed['buildings'] if x['building_id']==bid)['status']='demolished'
        from game.economy import storage
        before=storage(state);after=storage(proposed)
        # Also account for utility outages caused by demolishing a provider.
        for r in ('food','water','material'):
            held=sum(state['resources'][x] for x in MATERIALS) if r=='material' else state['resources'][r]
            from game.economy import food_lock
            protected=food_lock(state)['protected_food'] if r=='food' else 0
            protected_after=food_lock(proposed)['protected_food'] if r=='food' else 0
            lost_capacity=after[r]+1e-8<min(before[r],held)
            lost_protection=protected_after+1e-8<protected and held>after[r]+protected_after+1e-8
            if lost_capacity or lost_protection:raise ValueError('Use or move stored resources before reducing their storage capacity.')
        amounts=recovery(state,b)
        connection.execute("UPDATE citizens SET unemployed_since=? WHERE citizen_id IN (SELECT citizen_id FROM citizen_assignments WHERE building_id=? AND ended_at IS NULL)",(now,bid))
        connection.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='building_demolished' WHERE building_id=? AND ended_at IS NULL",(now,bid))
        connection.execute("UPDATE buildings SET status='demolished',current_hp=0,cleared_at=? WHERE building_id=?",(now,bid))
    current=read_state(connection)
    delivered=credit(connection,current,amounts,now)
    connection.execute('INSERT INTO building_state_events(building_id,event_type,occurred_at,event_data) VALUES (?,?,?,?)',(bid,action,now,json.dumps({'recovered':amounts,'delivered':delivered})))
    from game.population import rebalance
    rebalance(connection,read_state(connection),now)

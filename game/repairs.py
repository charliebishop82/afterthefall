"""Paid manual building repairs and slow staffed Town Hall regeneration."""
import json
from game.buildings import spec,productivity,coverage
from game.settlement import read_state


def enabled(state):return state['season']['config_version'] in ('prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13')


def enable(connection,state,now):
    if enabled(state):return
    from game.progression import enable as progression
    from game.simulation import _event
    progression(connection,state,now);state=read_state(connection)
    connection.execute("UPDATE seasons SET config_version='prototype_v8' WHERE season_id=?",(state['season']['season_id'],))
    _event(connection,state,'prototype_regen_clock',now,{'pending':0})
    _event(connection,state,'prototype_config_enabled',now,{'from':state['season']['config_version'],'to':'prototype_v8'})


def costs(state,building):
    missing=max(0,1-building['current_hp']/spec(state,building)['hp'])
    levels=state['config']['buildings'][building['building_type']]['levels'][:building['level']]
    return {r:sum(s[r] for s in levels)*state['config']['repairs']['material_fraction']*missing for r in ('scrap','metal','electronics')}


def command(connection,state,action,bid,cid,now,exposed=False):
    from game.simulation import _event
    if action=='enable_repairs':enable(connection,state,now);return
    if not enabled(state):raise ValueError('Enable building repairs first.')
    b=next((b for b in state['buildings'] if b['building_id']==bid),None)
    if not b or b['status']!='active' or b['current_hp']<=0 or b['building_type'] in ('pup_tent','upgraded_tent'):
        raise ValueError('Choose a completed, surviving permanent building.')
    job=next((j for j in state['jobs'] if j['target_building_id']==bid and j['status'] in ('active','paused')),None)
    if action=='repair':
        if b['building_type']=='town_hall' and state['regen_pending']:
            connection.execute('UPDATE buildings SET current_hp=min(current_hp+?,?) WHERE building_id=?',(state['regen_pending'],spec(state,b)['hp'],bid))
            _event(connection,state,'prototype_regen_clock',now,{'pending':0})
            state=read_state(connection);b=state['buildings'][0]
        if now>=state['season']['finalization_at'] or state['season']['status']=='finalizing':raise ValueError('New repair projects are closed during the final three hours.')
        if job:raise ValueError('This building already has a project.')
        if b['current_hp']>=spec(state,b)['hp']:raise ValueError('This building is already at full health.')
        price=costs(state,b)
        from game.trading import available
        if any(available(state,r)+1e-9<value for r,value in price.items()):raise ValueError('Not enough materials for repairs.')
        connection.execute('UPDATE settlement_resources SET scrap=scrap-?,metal=metal-?,electronics=electronics-?,updated_at=? WHERE settlement_id=?',(*price.values(),now,state['settlement']['settlement_id']))
        inputs={**price,'_start_hp':b['current_hp']}
        connection.execute("INSERT INTO settlement_jobs(settlement_id,job_type,target_type,target_building_id,work_required,status,created_at,last_processed_at,inputs_spent,pause_reason) VALUES (?,'repair','building',?,?,'paused',?,?,?,'Assign repair workers')",(state['settlement']['settlement_id'],bid,(spec(state,b)['hp']-b['current_hp'])/state['config']['repairs']['hp_per_worker_hour']*3600,now,now,json.dumps(inputs)))
    else:
        c=next((c for c in state['citizens'] if c['citizen_id']==cid and c['current_hp']>0),None)
        if not c or not job or job['job_type']!='repair':raise ValueError('Choose a living citizen and an active repair project.')
        if c['assignment']=='repair' and c['job_id']==job['job_id']:return
        if c['assignment']!='unassigned':raise ValueError('Release this citizen from their current job first.')
        if connection.execute('SELECT 1 FROM attack_citizens WHERE citizen_id=? AND released_at IS NULL',(cid,)).fetchone():raise ValueError('That citizen is away.')
        if b['building_type']!='town_hall' and coverage(state,b)<state['config']['construction']['coverage_fraction'] and (not exposed or 'consequences' not in state['config']):raise ValueError('Confirm dangerous Oxygen exposure before repair work.')
        aid=connection.execute("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,building_id,job_id,assigned_at) VALUES (?,?,'repair',?,?,?)",(cid,state['settlement']['settlement_id'],bid,job['job_id'],now)).lastrowid
        if exposed and 'consequences' in state['config'] and coverage(state,b)<state['config']['construction']['coverage_fraction']:
            from game.consequences import authorize
            authorize(connection,state,aid,now)
        connection.execute('UPDATE citizens SET unemployed_since=NULL WHERE citizen_id=?',(cid,))
    _event(connection,state,'prototype_repair_action',now,{'action':action,'building_id':bid,'citizen_id':cid})


def crew_speed(state,job):
    b=next(b for b in state['buildings'] if b['building_id']==job['target_building_id'])
    if b['status']!='active' or b['current_hp']<=0:return 0
    from game.consequences import deliberate
    if b['building_type']!='town_hall' and coverage(state,b)<state['config']['construction']['coverage_fraction'] and not all(deliberate(state,c) for c in state['citizens'] if c['job_id']==job['job_id']):return 0
    crew=[c for c in state['citizens'] if c['job_id']==job['job_id'] and c['assignment']=='repair']
    from game.support import best
    return sum(productivity(state,c) for c in crew)/len(crew)**(1-state['config']['construction']['worker_exponent'])*(1+best(state,'construction_bonus')/100) if crew else 0


def regen_rate(state):
    hall=state['buildings'][0]
    return state['config']['repairs']['town_hall_hp_per_hour'] if hall['status'] in ('active','upgrading') and hall['current_hp']>0 and any(c['assignment']=='administrator' and c['current_hp']>0 for c in state['citizens']) else 0


def speed(state,job):
    if job['status'] not in ('active','paused'):return 0
    hall=state['buildings'][0]
    from game.maintenance import building_speed
    return crew_speed(state,job)+building_speed(state,job)+(regen_rate(state)/state['config']['repairs']['hp_per_worker_hour'] if job['target_building_id']==hall['building_id'] else 0)


def tick(state,now):
    return (now-state['recovery_clock']['anchor'])%state['config']['recovery']['tick_seconds']==0 or now==state['season']['ends_at']


def next_boundary(state):
    if not enabled(state):return None
    hall=state['buildings'][0]
    if not state['regen_pending'] and not any(j['job_type']=='repair' and j['status'] in ('active','paused') for j in state['jobs']) and not (hall['current_hp']<spec(state,hall)['hp'] and regen_rate(state)):return None
    start=state['settlement']['simulation_processed_at'];anchor=state['recovery_clock']['anchor'];q=state['config']['recovery']['tick_seconds']
    return anchor+((start-anchor)//q+1)*q


def progress(connection,state,job,seconds,now):
    rate=speed(state,job);done=min(job['work_required'],job['work_completed']+rate*seconds)
    if job['work_required']-done<1e-7:done=job['work_required']
    complete=done==job['work_required'];b=next(b for b in state['buildings'] if b['building_id']==job['target_building_id'])
    connection.execute('UPDATE settlement_jobs SET work_completed=?,last_processed_at=?,status=?,pause_reason=?,completed_at=? WHERE job_id=?',(done,now,'completed' if complete else 'active' if rate else 'paused',None if rate else 'No effective repair workers or unsafe Oxygen coverage',now if complete else None,job['job_id']))
    if tick(state,now) or complete:
        hp=min(spec(state,b)['hp'],json.loads(job['inputs_spent'])['_start_hp']+done*state['config']['repairs']['hp_per_worker_hour']/3600)
        connection.execute('UPDATE buildings SET current_hp=? WHERE building_id=?',(hp,b['building_id']))
    if complete:
        connection.execute('UPDATE citizens SET unemployed_since=? WHERE citizen_id IN (SELECT citizen_id FROM citizen_assignments WHERE job_id=? AND ended_at IS NULL)',(now,job['job_id']))
        connection.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='completed' WHERE job_id=? AND ended_at IS NULL",(now,job['job_id']))
        connection.execute("INSERT INTO building_state_events(building_id,event_type,occurred_at,event_data) VALUES (?,'repair_completed',?,'{}')",(b['building_id'],now))
        from game.simulation import _event
        _event(connection,state,'building_repair_completed',now,{'building_id':b['building_id']})


def regenerate(connection,state,seconds,now):
    if not enabled(state):return
    hall=state['buildings'][0]
    if any(j['job_type']=='repair' and j['target_building_id']==hall['building_id'] and j['status'] in ('active','paused') for j in state['jobs']):return
    pending=state['regen_pending']
    if hall['current_hp']<spec(state,hall)['hp']:pending+=regen_rate(state)*seconds/3600
    if tick(state,now):
        if pending:
            level=connection.execute('SELECT level FROM buildings WHERE building_id=?',(hall['building_id'],)).fetchone()[0]
            connection.execute('UPDATE buildings SET current_hp=min(current_hp+?,?) WHERE building_id=?',(pending,spec(state,hall,level)['hp'],hall['building_id']))
        pending=0
    if pending!=state['regen_pending']:
        from game.simulation import _event
        _event(connection,state,'prototype_regen_clock',now,{'pending':pending})

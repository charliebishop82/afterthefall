"""Work-based citizen XP on the existing simulated-minute grid."""
import copy

from game.buildings import productivity,job_speed,spec
from game.settlement import read_state


def enabled(state):
    return state['season']['config_version'] in ('prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13')


def record(connection,state,now,clock):
    from game.simulation import _event
    _event(connection,state,'prototype_xp_clock',now,clock)


def enable(connection,state,now):
    if enabled(state):return
    from game.recovery import enable as enable_recovery
    enable_recovery(connection,state,now)
    state=read_state(connection)
    connection.execute("UPDATE seasons SET config_version='prototype_v7' WHERE season_id=?",(state['season']['season_id'],))
    record(connection,state,now,{'pending':{}})
    from game.simulation import _event
    _event(connection,state,'prototype_config_enabled',now,{'from':state['season']['config_version'],'to':'prototype_v7'})


def hourly_rates(state, seconds=None):
    """Equivalent productive work, including crew sharing and input throttling."""
    if not enabled(state):return {}
    from game.economy import utilities,rates,condition
    utility=utilities(state)
    rates(state,utility,seconds=seconds)  # Resource delivery and XP use the same useful work.
    result={};rules=state['config']['progression']
    hall=state['buildings'][0]
    for citizen in state['citizens']:
        factor=productivity(state,citizen);assignment=citizen['assignment'];value=0
        if assignment=='administrator' and hall['status'] in ('active','upgrading'):
            value=factor*condition(state,hall)*utility['hall_work_fraction']*rules['work_xp_per_hour']
            if hall['status']=='upgrading':value*=state['config']['construction']['town_hall_upgrade_productivity']
        elif assignment=='production':
            status=utility['buildings'].get(citizen['building_id'])
            if state['season']['config_version']in ('prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
                building=next((b for b in state['buildings'] if b['building_id']==citizen['building_id']),None)
                if building and building['building_type'] in ('drone_factory','munitions_factory'):
                    from game.manufacturing import speed
                    active=next((j for j in state['jobs'] if j['production_building_id']==building['building_id'] and j['status'] in ('active','paused') and j['job_type']=='manufacturing'),None)
                    if not active or speed(state,active)<=0:
                        continue
            if status and (not status['reason'] or status['reason'] in ('Limited by arriving input materials','Limited by output storage')):
                building=next(b for b in state['buildings'] if b['building_id']==citizen['building_id'])
                value=factor*condition(state,building)*status['work_fraction']*rules['work_xp_per_hour']
        if value>0:result[citizen['citizen_id']]=value
    for job in state['jobs']:
        if job['status'] not in ('active','paused'):continue
        speed=job_speed(state,job)
        if job['job_type']=='repair':
            from game.repairs import crew_speed
            speed=crew_speed(state,job)
        if speed<=0:continue
        crew=[c for c in state['citizens'] if c['job_id']==job['job_id']]
        total=sum(productivity(state,c) for c in crew)
        base=rules['construction_xp_per_hour'] if job['job_type'] in ('construction','upgrade','repair') else rules['work_xp_per_hour']
        for citizen in crew:
            result[citizen['citizen_id']]=speed*productivity(state,citizen)/total*base
    return result


def next_boundary(state):
    if not enabled(state):return None
    if not state['xp_clock']['pending'] and not hourly_rates(state):return None
    start=state['settlement']['simulation_processed_at'];anchor=state['recovery_clock']['anchor']
    quantum=state['config']['recovery']['tick_seconds']
    return anchor+((start-anchor)//quantum+1)*quantum


def accrue(connection,state,seconds,now):
    if not enabled(state) or seconds<=0:return
    clock=copy.deepcopy(state['xp_clock']);pending=clock['pending']
    earned=hourly_rates(state,seconds)
    # Completion boundaries round to whole seconds. Never award beyond actual work.
    for job in state['jobs']:
        if job['status'] not in ('active','paused'):continue
        speed=job_speed(state,job)
        if speed>0:
            fraction=min(1,max(0,job['work_required']-job['work_completed'])/(speed*seconds))
            for c in state['citizens']:
                if c['job_id']==job['job_id'] and c['citizen_id'] in earned:earned[c['citizen_id']]*=fraction
    for cid,value in earned.items():pending[str(cid)]=pending.get(str(cid),0)+value*seconds/3600
    quantum=state['config']['recovery']['tick_seconds']
    if (now-state['recovery_clock']['anchor'])%quantum==0 or now==state['season']['ends_at']:
        thresholds=state['config']['progression']['thresholds']
        for citizen in state['citizens']:
            xp=citizen['xp']+pending.get(str(citizen['citizen_id']),0)
            level=max(citizen['level'],sum(xp+1e-9>=threshold for threshold in thresholds))
            if xp!=citizen['xp'] or level!=citizen['level']:
                connection.execute('UPDATE citizens SET xp=?,level=? WHERE citizen_id=?',(xp,level,citizen['citizen_id']))
                for reached in range(citizen['level']+1,level+1):
                    connection.execute('INSERT INTO citizen_level_history(citizen_id,level,xp_total,reached_at) VALUES (?,?,?,?)',(citizen['citizen_id'],reached,xp,now))
        pending.clear()
    if clock!=state['xp_clock']:record(connection,state,now,clock)

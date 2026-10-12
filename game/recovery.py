"""Natural healing and reversible housing morale; no schema migration or timer."""
import copy

from game.settlement import read_state


def enabled(state):
    return state['season']['config_version'] in ('prototype_v6','prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13')


def record_clock(connection,state,now,clock):
    from game.simulation import _event
    _event(connection,state,'prototype_recovery_clock',now,clock)


def enable(connection,state,now):
    if enabled(state):return
    from game.population import enable as enable_housing
    enable_housing(connection,state,now)
    state=read_state(connection)
    connection.execute("UPDATE seasons SET config_version='prototype_v6' WHERE season_id=?",(state['season']['season_id'],))
    record_clock(connection,state,now,{'anchor':now,'pending':{}})
    from game.simulation import _event
    _event(connection,state,'prototype_config_enabled',now,{'from':state['season']['config_version'],'to':'prototype_v6'})


def max_hp(state,citizen):
    return state['config']['citizen_hp']+(citizen['level']-1)*state['config']['simulation']['hp_per_level']


def decorate(state):
    """Resolve utilities and housing with current morale, without recursive reads.

    Start without bonuses so a disconnected source cannot bootstrap itself with
    its own comfort benefit. If housing and utility supply oscillate, retain only
    consistently usable capacity; this conservatively avoids unsafe occupancy.
    """
    from game.economy import utilities
    from game.population import housing
    from game.needs import morale_modifier
    from game.support import community
    ration_morale=morale_modifier(state)
    for c in state['citizens']:
        c['exposure_morale_modifier']=state['config'].get('consequences',{}).get('exposure_morale',0) if str(c['citizen_id']) in state.get('consequences_clock',{}).get('exposed',{}) else 0
    seen={}; allocations=[]
    for c in state['citizens']:c['effective_morale']=min(100,max(0,c['morale']+state.get('debt_morale_modifier',0)+c.get('exposure_morale_modifier',0)+(ration_morale if not c.get('away') else 0)))
    for _ in range(32):
        allocation=housing(state,utility=utilities(state))
        community_bonus=community(state)
        for c in state['citizens']:c['community_morale_modifier']=community_bonus if not c.get('away') else 0
        modifiers={c['citizen_id']:(allocation['assignments'][c['citizen_id']]['quality']
                    if allocation['assignments'][c['citizen_id']] and not c.get('away') else 0) for c in state['citizens']}
        signature=(tuple(modifiers.items()),community_bonus)
        previous=tuple((c['citizen_id'],c.get('housing_morale_modifier',0)) for c in state['citizens'])
        if tuple(modifiers.items())==previous and all(abs(c['effective_morale']-min(100,max(0,c['morale']+state.get('debt_morale_modifier',0)+c.get('exposure_morale_modifier',0)+modifiers[c['citizen_id']]+c['community_morale_modifier']+(ration_morale if not c.get('away') else 0))))<1e-9 for c in state['citizens']):break
        if signature in seen:
            cycle=allocations[seen[signature]:]+[allocation]
            capacities={h['building_id']:min(next((x['capacity'] for x in a['homes'] if x['building_id']==h['building_id']),0)
                                            for a in cycle) for h in allocation['homes']}
            for h in allocation['homes']:h['capacity']=capacities[h['building_id']]
            slots=[h for h in sorted(allocation['homes'],key=lambda h:(-h['quality'],h['building_id'])) for _ in range(h['capacity'])]
            citizens=sorted(state['citizens'],key=lambda c:(-c['level'],-c['xp'],c['joined_at'],c['citizen_id']))
            allocation['assignments']={c['citizen_id']:slots[i] if i<len(slots) else None for i,c in enumerate(citizens)}
            allocation['capacity']=len(slots)
            allocation['homeless']=max(0,len(citizens)-len(slots))
            modifiers={cid:h['quality'] if h else 0 for cid,h in allocation['assignments'].items()}
            for c in state['citizens']:
                c['housing_morale_modifier']=modifiers[c['citizen_id']]
                c['effective_morale']=min(100,max(0,c['morale']+state.get('debt_morale_modifier',0)+c.get('exposure_morale_modifier',0)+modifiers[c['citizen_id']]+c['community_morale_modifier']+(ration_morale if not c.get('away') else 0)))
            break
        seen[signature]=len(allocations);allocations.append(allocation)
        for c in state['citizens']:
            c['housing_morale_modifier']=modifiers[c['citizen_id']]
            c['effective_morale']=min(100,max(0,c['morale']+state.get('debt_morale_modifier',0)+c.get('exposure_morale_modifier',0)+modifiers[c['citizen_id']]+c['community_morale_modifier']+(ration_morale if not c.get('away') else 0)))
    for c in state['citizens']:
        c.setdefault('housing_morale_modifier',0)
        c['max_hp']=max_hp(state,c)
    state['recovery_housing']=allocation


def eligibility(state):
    from game.economy import available_food
    from game.trading import available
    supplies=min(available_food(state),available(state,'water'))>0
    from game.needs import enabled,shortages
    if enabled(state):supplies=not any(shortages(state).values())
    return {c['citizen_id']:('Away on a raid' if c.get('away') else 'At full health' if c['current_hp']>=max_hp(state,c) else
             'Dangerous Oxygen exposure' if str(c['citizen_id']) in state.get('consequences_clock',{}).get('exposed',{}) else
             'No recovery at zero HP' if c['current_hp']<=0 else
             'Needs accessible Food and Water' if not supplies else
             'Needs safe housing' if state['recovery_housing']['assignments'][c['citizen_id']] is None else '')
            for c in state['citizens']}


def next_boundary(state):
    if not enabled(state):return None
    if not state['recovery_clock']['pending'] and all(eligibility(state).values()):return None
    start=state['settlement']['simulation_processed_at'];anchor=state['recovery_clock']['anchor']
    quantum=state['config']['recovery']['tick_seconds']
    return anchor+((start-anchor)//quantum+1)*quantum


def accrue(connection,state,seconds,now):
    if not enabled(state) or seconds<=0:return
    clock=copy.deepcopy(state['recovery_clock']);pending=clock['pending']
    from game.support import healing_rates
    healing=healing_rates(state)
    for cid,reason in eligibility(state).items():
        if not reason:pending[str(cid)]=pending.get(str(cid),0)+seconds*healing[cid]/state['config']['recovery']['natural_hp_per_hour']
    quantum=state['config']['recovery']['tick_seconds']
    if (now-clock['anchor'])%quantum==0:
        for c in state['citizens']:
            credit=pending.get(str(c['citizen_id']),0)
            if credit and c['current_hp']>0:
                hp=min(max_hp(state,c),c['current_hp']+credit/3600*state['config']['recovery']['natural_hp_per_hour'])
                connection.execute('UPDATE citizens SET current_hp=? WHERE citizen_id=?',(hp,c['citizen_id']))
        pending.clear()
    if clock!=state['recovery_clock']:record_clock(connection,state,now,clock)


def shift_clock(connection,state,seconds,now):
    from game.expeditions import shift_clock as expedition_shift
    expedition_shift(connection,state,seconds)
    from game.consequences import shift_clock as citizen_shift
    citizen_shift(connection,state,seconds,now)
    if state.get('expansion') and seconds:
        from game.banking import shift_clock as bank_shift
        bank_shift(connection,state,seconds)
        pending=[c['citizen_id'] for c in state['citizens'] if not c['integrated']]
        if pending:
            from game.simulation import _event
            _event(connection,state,'captured_integration_deferred',now,{'until':(now//86400+1)*86400,'citizens':pending})
    if enabled(state) and seconds:
        clock=copy.deepcopy(state['recovery_clock']);clock['anchor']+=seconds
        record_clock(connection,state,now,clock)

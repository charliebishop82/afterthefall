"""Read-only military inventory overview using existing readiness rules."""
from game import combat,structural

def payload(state):
    from game.economy import utilities
    specs=state['config'].get('units',{})
    homes={}
    if specs:
        operational=utilities(state)['buildings']
        homes={b['building_id']:not operational.get(b['building_id'],{}).get('reason',True)
               for b in state['buildings'] if b['status']=='active'}
    drones_enabled=state['season']['config_version'] in ('prototype_v10','prototype_v11','prototype_v12','prototype_v13')
    groups=[]
    for kind,spec in specs.items():
        units=[u for u in state.get('units',[]) if u['unit_type']==kind and u['status']!='destroyed']
        entries=[dict(id=u['unit_id'],hp=u['current_hp'],max_hp=spec['hp'],status=u['status'],home=u['home_building_id'],
                      ready=drones_enabled and u['status']=='available' and u['current_hp']>0 and homes.get(u['home_building_id'],False)) for u in units]
        inventory=[i for i in state.get('inventory',[]) if i['unit_type']==kind]
        ammo_ready=sum(i['quantity'] for i in inventory if homes.get(i['building_id'],False)) if structural.enabled(state) else 0
        ammo=sum(i['quantity'] for i in inventory)
        from game.manufacturing import compatible_home
        ammo_homes={b['building_id'] for b in state['buildings'] if compatible_home(state,kind,b)}
        deployed_ammo=sum(i['quantity'] for i in state.get('munition_reservations',[]) if i['building_id'] in ammo_homes)
        groups.append(dict(kind=kind,name=spec['name'],total=len(units)+ammo+deployed_ammo,
            ready=sum(bool(u['ready']) for u in entries)+ammo_ready,
            deployed=sum(u['status']=='deployed' for u in units)+deployed_ammo,
            damaged=sum(0<u['current_hp']<spec['hp'] for u in units),units=entries,ammunition=ammo,
            factory=spec['factory'],storage=spec['storage']))
    home=combat.home(state)
    floor=int(combat.rule('raid_home_population_min'))
    roles=('unassigned','administrator') if state['season']['config_version']=='prototype_v13' else ('unassigned',)
    eligible=[c for c in home if c['assignment'] in roles and c.get('integrated',True) and
              c['current_hp']/combat.maximum_hp(state,c)>=combat.rule('citizen_low_hp_raid_threshold')/100]
    jobs=[dict(id=j['job_id'],kind=j['output_type'],status=j['status'],reason=j.get('pause_reason'),
               percent=min(100,100*j['work_completed']/j['work_required']) if j['work_required'] else 0)
          for j in state['jobs'] if j['job_type']=='manufacturing' and j['status'] in ('queued','active','paused')]
    return dict(clock_running=state['season']['status'] in ('active','finalizing') and state['settlement']['status']=='active',equipment=groups,eligible_raiders=min(len(eligible),max(0,len(home)-floor)),home=len(home),home_minimum=floor,
        patrols=sum(c['assignment']=='patrol' for c in home),guards=sum(c['assignment']=='defender' for c in home),
        allowance=state['settlement']['attacks_remaining'],jobs=jobs,
        expeditions=[dict(id=e['expedition_id'],status=e['status'],seconds=max(0,e['returns_at']-state['settlement']['simulation_processed_at']),
                          crew=[c['name']+' (#'+str(c['id'])+')' for c in e.get('crew',[])])
                     for e in state.get('expeditions',[]) if e['status']!='returned'])

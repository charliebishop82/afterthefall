"""Civilian utility allocation and material conversion, using versioned settings."""

from game.buildings import rules, spec, footprint, productivity

from game.trading import available
from functools import lru_cache
from game.calculations import utility_allocation

MATERIALS = ('scrap', 'metal', 'electronics')


def condition(state, b):
    return min(1, b['current_hp'] / spec(state,b)['hp'])


def within_zone(state, x, y, b):
    w,h = footprint(state,b)
    dx=max(b['origin_x']-(x+.5),0,(x+.5)-(b['origin_x']+w))
    dy=max(b['origin_y']-(y+.5),0,(y+.5)-(b['origin_y']+h))
    return dx*dx+dy*dy <= spec(state,b)['radius']**2


@lru_cache(maxsize=8192)
def _coverage(bounds, zones):
    """Geometry-only cache: condition and staffing change the supplied zones."""
    x0,y0,w,h=bounds
    return sum(any(max(zx-(x+.5),0,(x+.5)-(zx+zw))**2
                   +max(zy-(y+.5),0,(y+.5)-(zy+zh))**2 <= radius**2
                   for zx,zy,zw,zh,radius in zones)
               for x in range(x0,x0+w) for y in range(y0,y0+h))/(w*h)


def coverage_fraction(state, x, y, w, h, zones):
    geometry=tuple((z['origin_x'],z['origin_y'],*footprint(state,z),spec(state,z)['radius']) for z in zones)
    return _coverage((x,y,w,h),geometry)


def zone_fraction(state, b, zones):
    return coverage_fraction(state,b['origin_x'],b['origin_y'],*footprint(state,b),zones)


@utility_allocation
def utilities(state):
    """Start from functioning self-starting sources; never bootstrap a utility cycle.

    Providers resolve before consumers. Dependents need coverage and remaining
    capacity. Within a priority tier, oldest completed building wins.
    """
    config=rules(state)
    hall=state['buildings'][0]
    hall_ok=hall['status'] in ('active','upgrading') and condition(state,hall)>config['construction']['shutdown_condition']
    if 'structural' in state['config']:hall_ok=True
    zones={u:[hall] if hall_ok else [] for u in ('oxygen','electricity')}
    capacity={u:spec(state,hall)[u+'_output']*condition(state,hall) if hall_ok else 0 for u in zones}
    if 'structural' in state['config']:
        base=state['config']['buildings']['town_hall']['levels'][0]
        capacity={u:max(capacity[u],base[u+'_output']) for u in zones}
    used=dict.fromkeys(zones,0.0)
    result={}
    pending=[]
    for b in state['buildings'][1:]:
        s=spec(state,b); info=config['buildings'][b['building_type']]
        workers=[c for c in state['citizens'] if c['building_id']==b['building_id'] and c['assignment']==('defender' if b['building_type']=='guard_post' else 'production')]
        factor=sum(productivity(state,c) for c in workers) if s['workers'] else 1
        reason=''
        housing=info['category']=='Housing'
        if b['status']!='active' and not (housing and b['status']=='upgrading'):reason='Construction in progress' if b['status']=='construction' else 'Upgrade in progress'
        elif condition(state,b)<=(0 if housing or b['building_type']=='vault' else config['construction']['shutdown_condition']):reason='Too damaged to operate'
        elif len([c for c in workers if productivity(state,c)>0])<info['workers_min']:reason=f"Requires {info['workers_min']} workers"
        result[b['building_id']]={'reason':reason,'workers':len(workers),'factor':factor*condition(state,b),
                                 'output':0,'outputs':{},'inputs':{}}
        if not reason:pending.append(b)
    priority={'Oxygen':0,'Electricity':0,'Housing':.5,'Medical':.6,'Water':1,'Food':2,'Defense':2.5,'Industry':3,'Drones':3,'Munitions':3,'Support':3}
    pending.sort(key=lambda b:(priority.get(config['buildings'][b['building_type']]['category'],4),
                               b['completed_at'] or b['created_at'],b['building_id']))
    # A provider may become reachable after another source starts. Each source
    # is accepted at most once; a disconnected circular pair cannot start itself.
    providers=[b for b in pending if spec(state,b)['oxygen_output'] or spec(state,b)['electricity_output']]
    consumers=[b for b in pending if b not in providers]
    def try_start(b):
        s=spec(state,b);info=config['buildings'][b['building_type']];status=result[b['building_id']]
        for u in zones:
            if info[u+'_required'] and zone_fraction(state,b,zones[u])<config['construction']['coverage_fraction']:
                status['reason']='Outside '+u+' coverage';return False
            if s[u+'_demand']>capacity[u]-used[u]+1e-9:
                status['reason']='Not enough '+u+' capacity';return False
        status['reason']=''
        for u in zones:
            used[u]+=s[u+'_demand']
            if s[u+'_output']:
                capacity[u]+=s[u+'_output']*status['factor'];zones[u].append(b)
        status['outputs']={r:s[key]*status['factor'] for r,key in
                           [('food','food'),('water','water'),('scrap','scrap_output'),('metal','metal_output'),('electronics','electronics_output')]
                           if s.get(key,0)}
        status['inputs']={r:s[r+'_input']*status['factor'] for r in ('scrap','metal') if s[r+'_input']}
        status['output']=status['outputs'].get('food',0)
        return True
    while providers:
        remaining=[b for b in providers if not try_start(b)]
        if len(remaining)==len(providers):break
        providers=remaining
    if state['season']['config_version'] not in ('prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
        for b in consumers:try_start(b)
    else:
        # Oxygen determines eligibility first; Electricity then uses its own
        # workbook priority. Retry lower Oxygen tiers with capacity released by
        # consumers that could not obtain Electricity. No idle reservation burns
        # capacity, and each candidate is considered at most once per tier pass.
        oxygen_order={'Housing':0,'Medical':1,'Water':2,'Food':2,'Industry':3,'Drones':3,'Munitions':3}
        electricity_order={'Water':1,'Food':2,'Medical':3,'Defense':4,'Industry':5,'Drones':5,'Munitions':5}
        def order(b,tiers,default):
            category=config['buildings'][b['building_type']]['category']
            if b['building_type'] in ('air_defense_bay','ground_defense_bay','interceptor_battery'):category='Defense'
            return (tiers.get(category,default),b['completed_at'] or b['created_at'],b['building_id'])
        candidates=[]
        for b in consumers:
            s=spec(state,b)
            missing=next((u for u in zones if config['buildings'][b['building_type']][u+'_required'] and zone_fraction(state,b,zones[u])<config['construction']['coverage_fraction']),None)
            if missing:result[b['building_id']]['reason']='Outside '+missing+' coverage'
            else:candidates.append(b)
        while candidates:
            oxygen_left=capacity['oxygen']-used['oxygen'];qualified=[];remaining=[]
            for b in sorted(candidates,key=lambda b:order(b,oxygen_order,4)):
                demand=spec(state,b)['oxygen_demand']
                if demand<=oxygen_left+1e-9:
                    qualified.append(b);oxygen_left-=demand
                else:
                    result[b['building_id']]['reason']='Not enough oxygen capacity';remaining.append(b)
            if not qualified:break
            for b in sorted(qualified,key=lambda b:order(b,electricity_order,6)):try_start(b)
            candidates=remaining

    return {'buildings':result,'zones':zones,'capacity':capacity,'used':used}


def storage(state, utility=None):
    utility=utility or utilities(state)
    hall=state['buildings'][0];hs=spec(state,hall)
    total={r:hs[r+'_storage']*condition(state,hall) for r in ('food','water','material')}
    for b in state['buildings'][1:]:
        if b['status'] not in ('active','upgrading'):continue
        s=spec(state,b); factor=condition(state,b)
        for r in total:
            capacity=s[r+'_storage']*factor
            if b['building_type']=='cold_storage' and utility['buildings'][b['building_id']]['reason']:
                capacity*=rules(state)['construction']['cold_storage_unpowered_fraction']
            total[r]+=capacity
    return total


def rates(state, utility=None, seconds=None):
    utility=utility or utilities(state);store=storage(state,utility)
    hall=state['buildings'][0];hs=spec(state,hall)
    admin=next((c for c in state['citizens'] if c['assignment']=='administrator'),None)
    factor=productivity(state,admin)*condition(state,hall) if admin and hall['status'] in ('active','upgrading') else 0
    if hall['status']=='upgrading':factor*=rules(state)['construction']['town_hall_upgrade_productivity']
    loot=dict.fromkeys(('food','water')+MATERIALS,0.0)
    from game.scavenging import speed
    import json
    for job in state['jobs']:
        if job['job_type']=='scavenging' and job['status'] in ('active','paused'):
            d=next(d for d in state['derelicts'] if d['settlement_derelict_id']==job['target_derelict_id'])
            totals=json.loads(d['random_result'])
            from game.support import best
            salvage_bonus=best(state,'salvage_bonus',utility)/100
            work=speed(state,job,utility=utility)/job['work_required']*3600
            for r in loot:
                bonus=salvage_bonus if r in MATERIALS else 0
                loot[r]+=totals[r]*work*(1+bonus)
    from game.production_flow import material_flow,supply_flow
    material_flow(state,utility,loot,store['material'],seconds)
    consumption={}
    for resource in ('food','water'):
        ration=rules(state)['simulation'][resource+'_per_citizen_per_hour']
        if state.get('needs_clock') is not None:
            ration=state['config']['needs']['rations'][resource][state['policies'][resource+'_ration']]['consumption']
        consumption[resource]=sum(not c.get('away') for c in state['citizens'])*ration
    hall_outputs={resource:hs[resource]*factor for resource in ('food','water')}
    supply_flow(state,utility,loot,store,hall_outputs,consumption,food_lock(state,utility)['protected_food'],seconds)
    result={}
    for r in ('food','water')+MATERIALS:
        production=(hall_outputs[r] if r in ('food','water') else 0)+sum(s['outputs'].get(r,0) for s in utility['buildings'].values())+loot[r]
        ration=rules(state)['simulation'][r+'_per_citizen_per_hour'] if r in ('food','water') else 0
        if r in ('food','water') and state.get('needs_clock') is not None:
            ration=state['config']['needs']['rations'][r][state['policies'][r+'_ration']]['consumption']
        consumption=(sum(not c.get('away') for c in state['citizens'])*ration if r in ('food','water') else 0)+sum(s['inputs'].get(r,0) for s in utility['buildings'].values())
        net=production-consumption
        result[r]=dict(production=production,consumption=consumption,net=net,
                       capacity=store[r if r in ('food','water') else 'material'],
                       hours_to_empty=available(state,r)/-net if net<0 else None)
    if result['food']['net']<0:
        result['food']['hours_to_empty']=available_food(state)/-result['food']['net']
    return result


def food_lock(state,utility=None):
    utility=utility or utilities(state)
    cap=storage(state,utility)['food']
    unpowered=[(b['building_id'],b['level']) for b in state['buildings'] if b['building_type']=='cold_storage'
               and b['status'] in ('active','upgrading') and utility['buildings'][b['building_id']]['reason']]
    signature=[list(pair) for pair in unpowered]
    old=state.get('storage_lock',{})
    if not signature:protected=0
    elif old.get('signature')==signature and old.get('capacity')==cap:
        protected=min(state['resources']['food'],old['protected_food'])
    else:protected=max(0,state['resources']['food']-cap)
    protected=min(protected,max(0,state['resources']['food']-state.get('reserved',{}).get('food',0)))
    return {'signature':signature,'capacity':cap,'protected_food':protected}


def available_food(state):
    return available(state,'food')


def production_status(state):
    utility=utilities(state)
    rates(state,utility)
    return utility['buildings']


def advance_resources(connection,state,seconds,now):
    """Industry runs until its input boundary; materials share one storage pool."""
    flow=rates(state,seconds=seconds); hours=seconds/3600; amounts={}
    for r in ('food','water'):
        old=state['resources'][r];cap=flow[r]['capacity']
        # Excess Cold Storage food remains inaccessible rather than being deleted.
        protected=food_lock(state)['protected_food'] if r=='food' else 0
        reserved=state.get('reserved',{}).get(r,0)
        held=protected+reserved
        usable=max(0,min(old-held,max(0,cap-reserved)))
        amounts[r]=held+max(0,min(max(0,cap-reserved),usable+flow[r]['net']*hours))
    material_hours=min([hours]+[available(state,r)/-flow[r]['net'] for r in MATERIALS if flow[r]['net']<0])
    for r in MATERIALS:
        amounts[r]=max(state.get('reserved',{}).get(r,0),state['resources'][r]+flow[r]['net']*material_hours)
    cap=flow['scrap']['capacity']; old_sum=sum(state['resources'][r] for r in MATERIALS)
    new_sum=sum(amounts[r] for r in MATERIALS)
    # Preserve legacy excess; never produce additional overflow.
    allowed=max(cap,old_sum)
    if new_sum>allowed:
        excess=new_sum-allowed
        gains={r:max(0,amounts[r]-state['resources'][r]) for r in MATERIALS}
        total=sum(gains.values())
        for r in MATERIALS:
            if total:amounts[r]-=excess*gains[r]/total
    connection.execute('''UPDATE settlement_resources SET food=?,water=?,scrap=?,metal=?,electronics=?,updated_at=?
        WHERE settlement_id=?''',tuple(amounts[r] for r in ('food','water')+MATERIALS)+(now,state['settlement']['settlement_id']))
    lock=food_lock(state)
    if lock!=state.get('storage_lock',{}) and (lock['signature'] or state.get('storage_lock')):
        from game.simulation import _event
        _event(connection,state,'prototype_food_storage_lock',now,lock)
    return amounts

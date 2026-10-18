"""Stable progression goals and purposeful, safe oxygen expansion."""
from game.buildings import rules,spec,footprint
from game.trading import available


def worker_reserve(personality,state=None,rates=None):
    base=2 if personality=='scavenger' else 1
    if not state:return base
    rates=rates or {}
    if any(j['job_type'] in ('construction','upgrade','repair') and j['status'] in ('active','paused') for j in state.get('jobs',[])):return 0
    if any(rates.get(r,{}).get('net',0)<0 for r in ('food','water')):return 0
    if state.get('buildings') and state['buildings'][0].get('level')==1 and state.get('config'):
        target=spec(state,state['buildings'][0],2)
        for r in ('scrap','metal','electronics'):
            if target[r]-available(state,r)>max(0,rates.get(r,{}).get('net',0)):return 0
    if personality=='scavenger' and any(e['status']!='returned' for e in state.get('expeditions',[])):return 1
    return base


def military_growth_allowed(state):
    hall=state['buildings'][0]
    return hall['level']>=2 or hall['status']=='upgrading'


def opening_upgrade(state,free,market,seed,action):
    hall=state['buildings'][0]
    if hall['level']!=1 or hall['status']!='active' or not free:return None
    if state['season']['status']!='active' or state['settlement']['simulation_processed_at']>=state['season']['finalization_at']:return None
    if any(j['job_type'] in ('construction','upgrade','repair') and j['status'] in ('active','paused') for j in state['jobs']):return None
    target=spec(state,hall,2)
    if all(available(state,r)>=target[r] for r in ('scrap','metal','electronics')):
        preparation=town_hall_preparation(state,free,market,seed,action)
        if preparation:return preparation
        return action('/buildings','Prioritize Town Hall 2 before optional military storage and upgrades.',action='upgrade',building_id=hall['building_id'],expected_level=1)
    from game.bot_market import choose_market
    return choose_market(state,{},seed,action,market,costs=target,purpose='the priority Town Hall upgrade')


def expansion_plan(state):
    """Find a reachable self-starting O2 provider that makes another ruin safe.

    Only geometry is predicted. Construction/staffing/capacity checks remain the
    responsibility of the ordinary player endpoints after each individual action.
    """
    from game.economy import utilities,coverage_fraction
    config=rules(state);hall=state['buildings'][0];threshold=config['construction']['coverage_fraction']
    zones=utilities(state)['zones']['oxygen']
    sites=[d for d in state['derelicts'] if d['status']!='cleared']
    if not sites:return None
    def fraction(site,providers):
        w,h=state['config']['derelicts'][site['derelict_type']]['footprint']
        return coverage_fraction(state,site['origin_x'],site['origin_y'],w,h,providers)
    before=[fraction(d,zones) for d in sites]
    if any(f>=threshold for f in before):return None
    occupied=[(b['origin_x'],b['origin_y'],*footprint(state,b)) for b in state['buildings'] if b['status'] not in ('cleared','demolished')]
    occupied += [(d['origin_x'],d['origin_y'],*state['config']['derelicts'][d['derelict_type']]['footprint']) for d in sites]
    kinds=[k for k,v in config['buildings'].items() if k!='town_hall' and v['unlock']<=hall['level'] and not v['oxygen_required'] and not v['electricity_required'] and v['workers_min']==0 and v['levels'][0].get('oxygen_output',0)>0 and v['levels'][0].get('radius',0)>0]
    best=None;best_score=None
    for kind in kinds:
        info=config['buildings'][kind]
        for rotation in ((0,90) if info['footprint'][0]!=info['footprint'][1] else (0,)):
            w,h=info['footprint'];w,h=(h,w) if rotation else (w,h)
            for x in range(config['map_width']-w+1):
                for y in range(config['map_height']-h+1):
                    if any(x<ox+ow and x+w>ox and y<oy+oh and y+h>oy for ox,oy,ow,oh in occupied):continue
                    if coverage_fraction(state,x,y,w,h,zones)<threshold:continue
                    candidate=dict(building_type=kind,origin_x=x,origin_y=y,rotation=rotation,level=1)
                    after=[fraction(site,zones+[candidate]) for site in sites]
                    gained=sum(f>=threshold for f in after)
                    if not gained:continue
                    distance=(x-hall['origin_x'])**2+(y-hall['origin_y'])**2
                    score=(gained,sum(after),-sum(info['levels'][0][r] for r in ('scrap','metal','electronics')),-distance)
                    if best_score is None or score>best_score:
                        best_score=score;best=dict(building_type=kind,x=x,y=y,rotation=rotation)
    return best


def expand_scavenging(state,free,market,seed,action):
    if not free or state['season']['status']!='active':return None
    if state['settlement']['simulation_processed_at']>=state['season']['finalization_at']:return None
    if any(j['job_type'] in ('construction','upgrade','repair') and j['status'] in ('active','paused') for j in state['jobs']):return None
    plan=expansion_plan(state)
    if not plan:return None
    target=rules(state)['buildings'][plan['building_type']]['levels'][0]
    if all(available(state,r)>=target[r] for r in ('scrap','metal','electronics')):
        return action('/buildings','Extend safe Oxygen coverage to unlock additional derelict scavenging sites.',action='build',**plan)
    from game.bot_market import choose_market
    return choose_market(state,{},seed,action,market,costs=target,purpose='extending safe scavenging coverage')


def supply_buffer(net,consumption,hours):
    return max(5,consumption*2)+max(0,-net)*hours


def town_hall_preparation(state,free,market,seed,action):
    from game.buildings import productivity
    from game.simulation import resource_rates
    from game.bot_market import purchase
    from game.bot_recovery import choose_supply
    hall=state['buildings'][0]
    future={**state,'buildings':[dict(b,status='upgrading') if b['building_id']==hall['building_id'] else b for b in state['buildings']]}
    rates=resource_rates(future)
    hours=spec(state,hall,hall['level']+1)['minutes']/60/max(.1,productivity(state,free[0]))
    gaps=[]
    for resource in ('food','water'):
        rate=rates[resource];required=supply_buffer(rate['net'],rate.get('consumption',0),hours)
        missing=required-available(state,resource)
        if missing>1e-8:gaps.append((resource,missing,required))
    if not gaps:return None
    for resource,missing,required in gaps:
        result=purchase(state,market,resource,missing,'the Town Hall upgrade supply buffer',action,emergency=True)
        if result:return result
    projected={k:dict(v) for k,v in rates.items()}
    for resource,_,_ in gaps:projected[resource]['net']=min(-.001,projected[resource]['net'])
    result=choose_supply(state,projected,free,market,action)
    if result:return result
    detail='; '.join(f'{r} {available(state,r):.1f}/{required:.1f}' for r,_,required in gaps)
    return action(None,'Waiting for Town Hall upgrade supplies: '+detail+'. Existing production or market supply must fill this buffer.')


def staff_active_project(state,free,rates,action):
    if not free:return None
    # Supply rescue takes precedence; do not absorb its last emergency operator.
    if any(rates.get(r,{}).get('net',0)<0 and available(state,r)<max(5,rates.get(r,{}).get('consumption',0)*2) for r in ('food','water')):return None
    from game.buildings import job_speed,coverage,productivity
    for job in state['jobs']:
        if job['job_type'] not in ('construction','upgrade','repair') or job['status'] not in ('active','paused'):continue
        building=next((b for b in state['buildings'] if b['building_id']==job['target_building_id']),None)
        if not building:continue
        if building['building_type']!='town_hall' and coverage(state,building)<rules(state)['construction']['coverage_fraction']:continue
        role='repair' if job['job_type']=='repair' else 'construction'
        if not any(c['job_id']==job['job_id'] and c['assignment']==role and not c.get('away') for c in state['citizens']):continue
        before=job_speed(state,job)
        worker=max(free,key=lambda c:productivity(state,c))
        virtual={**state,'citizens':[dict(c,assignment=role,job_id=job['job_id'],building_id=building['building_id']) if c['citizen_id']==worker['citizen_id'] else c for c in state['citizens']]}
        after=job_speed(virtual,job)
        if after>before+.05:
            return action('/buildings',f'Add a useful builder to {building["building_type"]}: project speed {before:.2f} to {after:.2f}; finish existing work before reserving idle staff.',action='repairer' if role=='repair' else 'builder',building_id=building['building_id'],citizen_id=worker['citizen_id'])
    return None


def reserve_wait_reason(state,free,rates,personality):
    projects=[j for j in state.get('jobs',[]) if j['job_type'] in ('construction','upgrade','repair') and j['status'] in ('active','paused')]
    if projects:
        j=projects[0];done=j.get('work_completed',0);total=j.get('work_required',0)
        return f'Waiting for {j["job_type"]} project #{j["job_id"]} ({100*done/total if total else 0:.0f}%); spare staff cannot safely improve its speed.'
    if personality=='scavenger':return 'Waiting: reserve idle citizens for an affordable expedition or the next essential project; no higher-priority eligible action was found.'
    return 'Waiting: reserve idle citizens for the next eligible construction or supply task; current material flow covers the opening goal within an hour.'

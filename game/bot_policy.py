"""Small economy decisions from this player's snapshot; no writes or opponents."""
import random
from game.buildings import spec, footprint, coverage, rules
from game.trading import available


POLICY_VERSION='workforce-v9'


def choose(state, rates, seed, personality='balanced', targets=None, market=None):
    def action(route,reason,**form):return dict(route=route,reason=reason,form=form,policy_version=POLICY_VERSION,personality=personality,seed=seed)
    rng=random.Random(seed)
    from game.bot_market import choose_market
    if state['season']['status'] not in ('active','finalizing') or state['settlement']['status']!='active':
        rescue=choose_market(state,rates,seed,action,market,emergency_only=True)
        return rescue or action(None,'Settlement or season is not running.')
    free=sorted([c for c in state['citizens'] if c['assignment']=='unassigned' and c['current_hp']>0 and not c.get('away')],key=lambda c:c['citizen_id'])
    from game.bot_expeditions import choose_expedition
    recall=choose_expedition(state,rates,seed,personality,action,free,recall_only=True)
    if recall:return recall
    if not any(c['assignment']=='administrator' and not c.get('away') for c in state['citizens']) and free:
        return action('/administrator','Restore Town Hall Administrator.',citizen_id=free[0]['citizen_id'])
    projects=[j for j in state['jobs'] if j['job_type'] in ('construction','upgrade','repair') and j['status'] in ('active','paused')]
    for job in projects:
        building=next(b for b in state['buildings'] if b['building_id']==job['target_building_id'])
        if not any(c['job_id']==job['job_id'] and not c.get('away') for c in state['citizens']) and free:
            if building['building_type']=='town_hall' or coverage(state,building)>=rules(state)['construction']['coverage_fraction']:
                return action('/buildings','Assign a builder to stalled construction.',action='repairer' if job['job_type']=='repair' else 'builder',building_id=building['building_id'],citizen_id=free[0]['citizen_id'])
    producers=[b for b in state['buildings'] if b['status']=='active' and b['building_type']!='town_hall' and spec(state,b)['workers']>0 and any(spec(state,b).get(k,0) for k in ('food','water','scrap_output','metal_output','electronics_output','oxygen_output','electricity_output'))]
    producers.sort(key=lambda b:(not any(rates.get(r,{}).get('net',0)<0 and spec(state,b).get(k,0)>0 for r,k in [('food','food'),('water','water')]),b['building_id']))
    for building in producers:
        if not any(c['building_id']==building['building_id'] and c['assignment']=='production' and not c.get('away') for c in state['citizens']) and free:
            if coverage(state,building)>=rules(state)['construction']['coverage_fraction']:
                return action('/buildings','Staff a completed production or utility building.',action='worker',building_id=building['building_id'],citizen_id=free[0]['citizen_id'])
    rescue=choose_market(state,rates,seed,action,market,emergency_only=True)
    if rescue:return rescue
    from game.bot_recovery import choose_supply,release_unsafe
    recovery=choose_supply(state,rates,free,market,action)
    if recovery:return recovery
    recovery=release_unsafe(state,action)
    if recovery:return recovery
    from game.bot_strategy import opening_upgrade,military_growth_allowed,expand_scavenging
    priority=opening_upgrade(state,free,market,seed,action) if all(rates.get(r,{}).get('net',0)>=0 for r in ('food','water')) else None
    if priority:return priority
    from game.bot_strategy import staff_active_project
    staffing=staff_active_project(state,free,rates,action)
    if staffing:return staffing
    from game.bot_equipment import choose_equipment
    funding=choose_equipment(state,rates,market,personality,seed,action,sell_only=True)
    if funding:return funding
    expedition=choose_expedition(state,rates,seed,personality,action,free)
    if expedition:return expedition
    if state.get('config',{}).get('units') and not any(state['resources'][r]<=0 or rates.get(r,{}).get('net',0)<0 for r in ('food','water')):
        from game.bot_military import choose_military,combat_decision
        if rng.random()<{'aggressive':.8,'defensive':.7,'balanced':.35,'builder':.2,'scavenger':.1}.get(personality,.35):
            military=(choose_military(state,targets or [],personality,seed,action,free,market,rates=rates) if military_growth_allowed(state) else combat_decision(state,targets or [],personality,seed,action))
            if military:return military
    # Look ahead with one scavenger freed, but submit the normal Release action first.
    if not free:
        worker=next((c for c in state['citizens'] if c['assignment']=='scavenging' and not c.get('away')),None)
        if worker:
            virtual={**state,'citizens':[dict(c,assignment='unassigned',job_id=None,building_id=None) if c['citizen_id']==worker['citizen_id'] else c for c in state['citizens']]}
            next_step=choose(virtual,rates,seed,personality,targets,market)
            if next_step['route'] in ('/buildings','/administrator','/conflict'):
                job=next(j for j in state['jobs'] if j['job_id']==worker['job_id'])
                return action('/scavenging','Free a scavenger for construction or essential production.',action='release',derelict_id=job['target_derelict_id'],citizen_id=worker['citizen_id'])
    if not projects and free and state['season']['status']=='active' and state['settlement']['simulation_processed_at']<state['season']['finalization_at']:
        catalog=rules(state)['buildings'];hall=state['buildings'][0]
        owned={b['building_type'] for b in state['buildings'] if b['status'] not in ('cleared','demolished','ruined')}
        from game.economy import storage
        from game.population import housing
        store=storage(state);homeless=housing(state)['homeless']
        urgent=any(state['resources'][r]<=0 or rates.get(r,{}).get('net',0)<0 for r in ('food','water'))
        allow_growth=personality!='scavenger' or urgent or rng.random()>=.35
        missing_utilities=set()
        if state['config'].get('units'):
            from game.economy import utilities
            for status in utilities(state)['buildings'].values():
                reason=(status.get('reason') or '').lower()
                for utility in ('oxygen','electricity'):
                    if 'not enough '+utility in reason:missing_utilities.add(utility)
        upgrades=[b for b in state['buildings'] if b['status']=='active' and b['building_type']!='town_hall' and b['level']<catalog[b['building_type']]['max_level']]
        rng.shuffle(upgrades)
        for b in upgrades:
            current=spec(state,b);target=spec(state,b,b['level']+1)
            needed=any(rates.get(r,{}).get('net',0)<0 and target.get(r,0)>current.get(r,0) for r in ('food','water'))
            needed=needed or (sum(state['resources'][r] for r in ('scrap','metal','electronics'))>=store['material']*.8 and target['material_storage']>current['material_storage'])
            needed=needed or (homeless>0 and target['housing']>current['housing'])
            needed=needed or any(state['resources'][r]>=store[r]*.8 and rates.get(r,{}).get('net',0)>0 and target[r+'_storage']>current[r+'_storage'] for r in ('food','water'))
            needed=needed or any(target.get(u+'_output',0)>current.get(u+'_output',0) for u in missing_utilities)
            needed=needed or (personality=='builder' and any(target.get(k,0)>current.get(k,0) for k in ('scrap_output','metal_output','electronics_output','oxygen_output','electricity_output')))
            if needed and all(available(state,r)>=target[r] for r in ('scrap','metal','electronics')):
                return action('/buildings','Upgrade '+b['building_type']+' to relieve an output, housing or storage constraint.',action='upgrade',building_id=b['building_id'],expected_level=b['level'])
            if needed:
                supplies=choose_market(state,rates,seed,action,market,costs=target,purpose='the '+b['building_type']+' upgrade')
                if supplies:return supplies
        if not allow_growth:
            # No essential shortage: a scavenger sometimes chooses recovery over expansion.
            return choose_scavenging(state,free,seed,action,rates,market,personality)
        wanted=[]
        for output in ('food','water','scrap_output','metal_output','electronics_output','oxygen_output','electricity_output'):
            if not any(spec(state,b).get(output,0) for b in producers):
                candidates=[k for k,v in catalog.items() if k!='town_hall' and v['levels'][0].get(output,0)>0]
                candidates.sort(key=lambda k:(catalog[k]['unlock'],sum(catalog[k]['levels'][0].get(r,0) for r in ('scrap','metal','electronics'))))
                wanted+=candidates[:1]
        from game.economy import storage
        cap=storage(state)
        if sum(state['resources'][r] for r in ('scrap','metal','electronics'))>=cap['material']*.8:
            wanted=['warehouse']+wanted
        from game.population import housing
        if housing(state)['homeless']:
            wanted=[k for k,v in catalog.items() if k!='town_hall' and v['levels'][0].get('housing',0)>0]+wanted
        occupied=[(b['origin_x'],b['origin_y'],*footprint(state,b)) for b in state['buildings'] if b['status'] not in ('cleared','demolished')]
        occupied += [(d['origin_x'],d['origin_y'],*state['config']['derelicts'][d['derelict_type']]['footprint']) for d in state['derelicts'] if d['status']!='cleared']
        for kind in dict.fromkeys(wanted):
            if kind not in catalog or kind in owned or hall['level']<catalog[kind]['unlock']:continue
            target=catalog[kind]['levels'][0]
            from game.bot_military import build_plan
            if any(available(state,r)<target[r] for r in ('scrap','metal','electronics')):
                if market and build_plan(state,kind,ignore_cost=True):
                    supplies=choose_market(state,rates,seed,action,market,costs=target,purpose='building '+kind)
                    if supplies:return supplies
                continue
            plan=build_plan(state,kind)
            if plan:return action('/buildings','Build missing economy infrastructure: '+kind+'.',action='build',**plan)
        if hall['level']<catalog['town_hall']['max_level']:
            target=spec(state,hall,hall['level']+1)
            if all(available(state,r)>=target[r] for r in ('scrap','metal','electronics')):
                from game.bot_strategy import town_hall_preparation
                preparation=town_hall_preparation(state,free,market,seed,action)
                if preparation:return preparation
                return action('/buildings','Upgrade Town Hall to unlock infrastructure.',action='upgrade',building_id=hall['building_id'],expected_level=hall['level'])
            supplies=choose_market(state,rates,seed,action,market,costs=target,purpose='the Town Hall upgrade')
            if supplies:return supplies
    expansion=expand_scavenging(state,free,market,seed,action)
    if expansion:return expansion
    surplus=choose_market(state,rates,seed,action,market)
    if surplus:return surplus
    return choose_scavenging(state,free,seed,action,rates,market,personality)


def choose_scavenging(state,free,seed,action,rates=None,market=None,personality='balanced'):
    from game.bot_strategy import worker_reserve,reserve_wait_reason
    if free and len(free)<=worker_reserve(personality,state,rates):
        return action(None,reserve_wait_reason(state,free,rates,personality))
    if free:
        from game.economy import storage
        material_full=sum(state['resources'][r] for r in ('scrap','metal','electronics'))>=storage(state)['material']-1e-8
        from game.scavenging import safe_coverage
        sites=[] if material_full else [d for d in state['derelicts'] if d['status']!='cleared' and safe_coverage(state,d)>=rules(state)['construction']['coverage_fraction']]
        rng=random.Random(seed);rng.shuffle(sites)
        for site in sites:
            count=sum(c['job_id']==j['job_id'] for j in state['jobs'] if j['target_derelict_id']==site['settlement_derelict_id'] and j['status'] in ('active','paused') for c in state['citizens'])
            if count<state['config']['derelicts'][site['derelict_type']]['workers']:
                return action('/scavenging','Assign an available citizen to safe scavenging.',action='assign',derelict_id=site['settlement_derelict_id'],citizen_id=free[0]['citizen_id'])
    from game.bot_recovery import idle_reason
    reason=idle_reason(state,free,rates,market)
    if any(j['job_type'] in ('construction','upgrade','repair') and j['status'] in ('active','paused') for j in state.get('jobs',[])):
        reason+=' '+reserve_wait_reason(state,free,rates,personality)
    return action(None,reason)

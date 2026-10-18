"""Recovery planning using ordinary player rules and public market data only."""
from game.buildings import spec,rules,coverage
from game.trading import available


def choose_supply(state,rates,free,market,action):
    if not free or any(j['job_type'] in ('construction','upgrade','repair') and j['status'] in ('active','paused') for j in state['jobs']):return None
    if state['season']['status']!='active' or state['settlement']['simulation_processed_at']>=state['season']['finalization_at']:return None
    from game.bot_military import build_plan
    from game.bot_market import choose_market
    catalog=rules(state)['buildings']
    for resource in ('water','food'):
        if rates.get(resource,{}).get('net',0)>=0:continue
        for building in state['buildings']:
            if building['building_type']=='town_hall' or building['status']!='active' or spec(state,building).get(resource,0)<=0:continue
            workers=sum(c['assignment']=='production' and c['building_id']==building['building_id'] and not c.get('away') for c in state['citizens'])
            if workers<spec(state,building)['workers'] and coverage(state,building)>=rules(state)['construction']['coverage_fraction']:
                return action('/buildings','Add operating staff to resolve the '+resource+' deficit.',action='worker',building_id=building['building_id'],citizen_id=free[0]['citizen_id'])
        candidates=[k for k,v in catalog.items() if k!='town_hall' and v['levels'][0].get(resource,0)>0]
        candidates.sort(key=lambda k:(sum(catalog[k]['levels'][0][r] for r in ('scrap','metal','electronics')),catalog[k]['unlock']))
        for kind in candidates:
            plan=build_plan(state,kind,ignore_cost=True)
            if not plan:continue
            cost=catalog[kind]['levels'][0]
            if all(available(state,r)>=cost[r] for r in ('scrap','metal','electronics')):
                return action('/buildings','Build additional '+kind+' to resolve the '+resource+' deficit.',action='build',**plan)
            decision=choose_market(state,rates,0,action,market,costs=cost,purpose='resolving the '+resource+' deficit')
            if decision:return decision
    return None


def release_unsafe(state,action):
    from game.scavenging import safe_coverage
    for job in state['jobs']:
        if job['job_type']!='scavenging' or job['status']!='paused':continue
        site=next((d for d in state['derelicts'] if d['settlement_derelict_id']==job['target_derelict_id']),None)
        if not site or safe_coverage(state,site)>=rules(state)['construction']['coverage_fraction']:continue
        worker=next((c for c in state['citizens'] if c['assignment']=='scavenging' and c['job_id']==job['job_id'] and not c.get('away')),None)
        if worker:return action('/scavenging','Release a worker from scavenging paused outside safe oxygen coverage.',action='release',derelict_id=site['settlement_derelict_id'],citizen_id=worker['citizen_id'])
    return None


def idle_reason(state,free,rates=None,market=None):
    from game.economy import storage
    from game.scavenging import safe_coverage
    reasons=[];rates=rates or {}
    if not free:reasons.append('no healthy idle home citizens')
    if sum(state['resources'][r] for r in ('scrap','metal','electronics'))>=storage(state)['material']-1e-8:reasons.append('material storage full')
    for r in ('food','water'):
        if rates.get(r,{}).get('net',0)<0:reasons.append(r+' production below consumption')
    if not any(d['status']!='cleared' and safe_coverage(state,d)>=rules(state)['construction']['coverage_fraction'] for d in state['derelicts']):reasons.append('no uncleared sites inside safe oxygen coverage')
    if market and market.get('can_trade'):
        for r in ('metal','electronics'):
            row=market['resources'].get(r,{})
            if row.get('stock',0)<=0 and row.get('reserve_remaining',0)<=0:reasons.append(r+' unavailable from shared stock and daily reserve')
    return 'Waiting: '+('; '.join(reasons) if reasons else 'no affordable eligible plan; remaining candidates may require unlocks, utility coverage or supplies')+'.'

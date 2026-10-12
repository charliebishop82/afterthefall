"""Personality-weighted expeditions using normal provision and recall rules."""
import math
import random
from game.trading import available

PROFILES={
    'scavenger':dict(chance=.75,hours=6,crew=2,home=2),
    'balanced':dict(chance=.30,hours=3,crew=1,home=3),
    'builder':dict(chance=.20,hours=2,crew=1,home=3),
    'aggressive':dict(chance=.15,hours=1.5,crew=1,home=6),
    'defensive':dict(chance=.10,hours=1,crew=1,home=6),
}

def choose_expedition(state,rates,seed,personality,action,free,*,recall_only=False):
    if 'expeditions' not in state or state['season']['status']!='active' or state['settlement']['status']!='active':return None
    now=state['settlement']['simulation_processed_at']
    if now>=state['season']['finalization_at']:return None
    active=[r for r in state['expeditions'] if r['status']!='returned']
    from game.economy import storage
    cap=storage(state)
    material_room=max(0,cap['material']-sum(state['resources'][r] for r in ('scrap','metal','electronics')))
    for row in active:
        if row['status']!='exploring':continue
        urgent=any(rates.get(r,{}).get('net',0)<0 and available(state,r)<max(5,rates.get(r,{}).get('consumption',0)*2) for r in ('food','water'))
        stalled=not free and any(j['job_type'] in ('construction','upgrade','repair') and j['status'] in ('active','paused') and
            not any(c['job_id']==j['job_id'] and not c.get('away') for c in state['citizens']) for j in state['jobs'])
        import json
        haul=sum(json.loads(row['yields']).values())*max(0,now-row['started_at'])/3600
        if urgent or stalled or material_room<=haul:
            reason='home supply pressure' if urgent else 'a stalled project needs workers' if stalled else 'storage is filling'
            return action('/expeditions','Recall explorers because '+reason+'; return uses the normal travel time.',action='recall',expedition_id=row['expedition_id'])
    if recall_only or active or not free:return None
    if any(j['job_type'] in ('construction','upgrade','repair') and j['status'] in ('active','paused') for j in state['jobs']):return None
    if any(rates.get(r,{}).get('net',0)<0 for r in ('food','water')):return None
    profile=PROFILES.get(personality,PROFILES['balanced'])
    if random.Random(seed).random()>=profile['chance']:return None
    home=sum(not c.get('away') for c in state['citizens'])
    # Keep an idle citizen available as well as the personality's home minimum.
    limit=min(profile['crew'],max(0,home-profile['home']),max(0,len(free)-1))
    eligible=sorted([c for c in free if c.get('integrated',True)],key=lambda c:(-c['level'],c['citizen_id']))[:limit]
    if not eligible:return None
    from game.expeditions import settings
    config=settings();normal=state['config'].get('simulation')
    if not normal:
        from game.settlement import load_config
        normal=load_config('prototype_v2')['simulation']
    crew=len(eligible);travel=config['return_minutes']/60
    yield_rate=sum(config['yield_per_hour'].values())*sum(1+(c['level']-1)*config['level_bonus'] for c in eligible)
    own_flow=sum(max(0,rates.get(r,{}).get('net',0)) for r in ('scrap','metal','electronics'))
    hours=min(profile['hours'],config['max_hours'],
              (state['season']['ends_at']-now)/3600-travel,
              max(0,material_room-own_flow*travel)/(yield_rate+own_flow))
    if hours<.5:return None
    packed={}
    for r in ('food','water'):
        packed[r]=math.floor(crew*normal[r+'_per_citizen_per_hour']*(hours+travel))
        if packed[r]<1:return None
        keep=max(12,rates.get(r,{}).get('consumption',0)*6)
        if available(state,r)-packed[r]<keep:return None
    hours=min(packed[r]/(crew*normal[r+'_per_citizen_per_hour']) for r in ('food','water'))-travel
    if hours<.5:return None
    return action('/expeditions',f'{personality.title()} exploration: send {crew} idle citizen(s), provision about {hours:g} hours, and preserve home supplies/workers.',
                  action='launch',citizen_id=[c['citizen_id'] for c in eligible],**packed)

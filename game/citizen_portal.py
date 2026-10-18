"""Read-only citizen card data; all actions remain in existing manual controls."""
from game.combat import maximum_hp

def data(state,citizen):
    cid=citizen['citizen_id'];role=citizen['assignment'];away=bool(citizen.get('away'))
    target='#citizens';label='View roster';return_seconds=None
    if citizen.get('exploring'):
        target='#expeditions';label='Manage expedition / recall'
        trip=next((r for r in state.get('expeditions',[]) if r['status']!='returned' and any(p['id']==cid for p in r.get('crew',[]))),None)
        if trip:return_seconds=max(0,trip['returns_at']-state['settlement']['simulation_processed_at'])
    elif away:target='#conflict';label='View raid status'
    elif citizen.get('building_id'):
        b=next((b for b in state['buildings'] if b['building_id']==citizen['building_id']),None)
        if b:target='#town-hall' if b['building_type']=='town_hall' else '#building-'+str(b['building_id']);label='Manage assigned building'
    elif citizen.get('job_id'):
        job=next((j for j in state['jobs'] if j['job_id']==citizen['job_id']),None)
        if job and job.get('target_derelict_id'):target='#derelict-'+str(job['target_derelict_id']);label='Manage scavenging crew'
    elif role in ('patrol','defender'):target='#support';label='Manage defense assignment'
    display='Exploring the Wastes' if citizen.get('exploring') else 'Raiding' if away else role.replace('_',' ').title()
    return dict(id=cid,name=citizen['name'],level=citizen['level'],xp=citizen['xp'],
        hp=citizen['current_hp'],max_hp=maximum_hp(state,citizen),
        morale=citizen.get('effective_morale',citizen['morale']),assignment=display,
        free=role=='unassigned' and not away and citizen['current_hp']>0,away=away,
        captured=not citizen.get('integrated',True),target=target,target_label=label,return_seconds=return_seconds)

def payload(state):return [data(state,c) for c in state['citizens']]

"""Cheap explanations of conservative bulk guards; no simulation or DB writes."""
from collections import Counter


def bulk_blockers(state):
    from game import progression,recovery
    from game.buildings import spec
    if not progression.enabled(state) or not recovery.enabled(state):
        return ['legacy detailed profile']
    reasons=[]
    from game.quiet import job_blocks_bulk
    jobs=Counter((j['status'],j['job_type']) for j in state['jobs'] if job_blocks_bulk(state,j))
    reasons.extend(f'{status} {kind} ({count})' for (status,kind),count in sorted(jobs.items()))
    if state['xp_clock']['pending']:reasons.append('partial-minute XP pending')
    if state['recovery_clock']['pending'] or state.get('regen_pending'):reasons.append('healing/repair credit pending')
    clock=state.get('needs_clock')
    if clock and (clock['pending'] or any(v is not None for v in clock['since'].values())):
        reasons.append('shortage health clock')
    if state.get('consequences_clock',{}).get('exposed'):reasons.append('Oxygen exposure')
    if any(state.get('reserved',{}).values()):reasons.append('reserved resources')
    if any(b['status']!='active' or b['current_hp']<spec(state,b)['hp'] for b in state['buildings']):
        reasons.append('building condition/work')
    home=[c for c in state['citizens'] if not c.get('away')]
    if any(c['current_hp']<recovery.max_hp(state,c) for c in home):reasons.append('injured citizens')
    if any(c.get('homeless_since') is not None for c in home):reasons.append('homelessness')
    assigned=state['recovery_housing']['assignments']
    homes=[assigned[c['citizen_id']] for c in home]
    if any(h is None for h in homes) or len({h['quality'] for h in homes if h})>1:
        reasons.append('housing allocation/quality')
    if any(spec(state,b).get('scrap_input',0) or spec(state,b).get('metal_input',0)
           for b in state['buildings'][1:] if b['status']=='active'):
        reasons.append('material converter')
    return reasons

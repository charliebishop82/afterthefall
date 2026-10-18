"""Conservative bulk XP for stable rates; stop before storage/supply transitions.

Other simulation boundaries still apply. Mutable or uncertain situations use
the original minute steps. XP level-ups retain their original minute boundary.
"""
import math
import json


def job_blocks_bulk(state,job):
    """An unfinished paused scavenging site with no assigned crew is inert.

    Do not infer inactivity from a status label alone: workers might resume,
    a completion may need cleanup, or a survivor roll may already be due.
    Other bulk guards and normal event boundaries still apply.
    """
    if job.get('status') not in ('active','paused','queued'):
        return False
    if job.get('status')!='paused' or job.get('job_type')!='scavenging':
        return True
    jid=job.get('job_id')
    if jid is None or any(c.get('job_id')==jid for c in state['citizens']):
        return True
    required=job.get('work_required',0);done=job.get('work_completed',0)
    if required<=0 or required-done<=1e-7:
        return True
    derelict=next((d for d in state['derelicts']
                   if d['settlement_derelict_id']==job.get('target_derelict_id')),None)
    if derelict is None or derelict['status']=='cleared':
        return True
    try:
        loot=json.loads(derelict['random_result'])
    except (ValueError,TypeError):
        return True
    if not isinstance(loot,dict):
        return True
    event=loot.get('_survivor')
    if event and not event['resolved'] and done/required+1e-9>=event['at_fraction']:
        return True
    return False


def eligible(state):
    from game import progression, recovery
    from game.buildings import spec
    if not progression.enabled(state) or not recovery.enabled(state):
        return False
    if state['xp_clock']['pending'] or state['recovery_clock']['pending'] or state.get('regen_pending'):
        return False
    if state.get('needs_clock') and (state['needs_clock']['pending'] or any(
            value is not None for value in state['needs_clock']['since'].values())):
        return False
    if state.get('consequences_clock',{}).get('exposed') or any(state.get('reserved',{}).values()):
        return False
    if any(job_blocks_bulk(state,j) for j in state['jobs']):
        return False
    if any(b['status']!='active' or b['current_hp'] < spec(state,b)['hp'] for b in state['buildings']):
        return False
    if any(c['current_hp'] < recovery.max_hp(state,c) or c.get('homeless_since') is not None
           for c in state['citizens'] if not c.get('away')):
        return False
    # XP can reorder housing priority before a level-up. Bulk only when that
    # reordering cannot change anyone's housing morale or productive rate.
    homes=state['recovery_housing']['assignments']
    occupied=[homes[c['citizen_id']] for c in state['citizens'] if not c.get('away')]
    if any(h is None for h in occupied) or len({h['quality'] for h in occupied})>1:
        return False
    from game.economy import rates
    flow=rates(state)
    # Converters can change rate when their input mix changes. Keep their
    # original detailed processing, even when one happens to be unstaffed.
    if any(spec(state,b).get('scrap_input',0) or spec(state,b).get('metal_input',0)
           for b in state['buildings'][1:] if b['status']=='active'):
        return False
    if any(state['resources'][r]<=0 or flow[r]['capacity']<=0 for r in ('food','water')):
        return False
    # Stay on the original minute grid before any stock boundary. The last
    # minute that fills/empties storage retains the original work throttling.
    boundary=stock_boundary(state,flow)
    return boundary is None or boundary>state['settlement']['simulation_processed_at']


def stock_boundary(state,flow=None):
    from game.economy import rates
    flow=rates(state) if flow is None else flow
    start=state['settlement']['simulation_processed_at'];times=[]
    anchor=state['recovery_clock']['anchor'];q=state['config']['recovery']['tick_seconds']
    for r in ('food','water'):
        net=flow[r]['net'];stock=state['resources'][r]
        if net>1e-12:
            times.append(start+max(0,flow[r]['capacity']-stock)/net*3600)
        elif net < -1e-12:
            times.append(start+stock/-net*3600)
    net=sum(flow[r]['net'] for r in ('scrap','metal','electronics'))
    if net>1e-12:
        room=max(0,flow['scrap']['capacity']-sum(state['resources'][r] for r in ('scrap','metal','electronics')))
        times.append(start+room/net*3600)
    # Negative material flow is excluded by the converter guard above.
    if not times:return None
    return anchor+math.floor((min(times)-anchor)/q)*q


def xp_boundary(state):
    from game.progression import hourly_rates
    start=state['settlement']['simulation_processed_at']
    anchor=state['recovery_clock']['anchor'];q=state['config']['recovery']['tick_seconds']
    times=[];earned=hourly_rates(state)
    thresholds=state['config']['progression']['thresholds']
    for c in state['citizens']:
        rate=earned.get(c['citizen_id'],0)
        if rate<=0:
            continue
        threshold=next((v for v in thresholds if v>c['xp']+1e-9),None)
        if threshold is not None:
            reaches=start+max(0,(threshold-c['xp']-1e-9)/rate*3600)
            times.append(max(anchor+((start-anchor)//q+1)*q,
                             anchor+math.ceil((reaches-anchor)/q)*q))
    stock_at=stock_boundary(state)
    if stock_at is not None:times.append(stock_at)
    return min(times) if times else None


def round_target(state,target):
    """Flush completed XP minutes before a final partial minute, as before."""
    if not eligible(state):
        return target
    anchor=state['recovery_clock']['anchor'];q=state['config']['recovery']['tick_seconds']
    last=anchor+((target-anchor)//q)*q
    return last if last>state['settlement']['simulation_processed_at'] else target

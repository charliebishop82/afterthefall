"""Construction, civilian/military staffing and upgrade presentation."""

import hashlib
import json
import math
from html import escape

from game.buildings import rules, spec, footprint, coverage, operating_status, job_speed, expanded


def material_market_link(state, costs):
    """Navigation only: reserved materials cannot satisfy construction costs."""
    from game.trading import available
    missing = [f'{max(0, costs[r]-available(state,r)):g} {r.title()}'
               for r in ('scrap','metal','electronics') if costs[r] > available(state,r)]
    if not missing:
        return ''
    return ('<span class="material-shortfall">Need '+escape(', '.join(missing))+
            ' more. <a href="#market">Buy missing materials at the market</a></span>')


def job_eta(state, job, speed=None):
    """Estimate remaining work with current effective crew speed."""
    if state['season']['status']=='paused': return 'Paused'
    if state['season']['status']=='finished': return 'Ended'
    if state['settlement']['status']!='active': return 'Frozen'
    if job['work_completed']>=job['work_required']: return 'Done'
    speed=job_speed(state,job) if speed is None else speed
    if speed<=0: return 'Waiting'
    minutes=max(1,math.ceil((job['work_required']-job['work_completed'])/speed/60))
    return f'{minutes}m' if minutes<60 else f'{minutes//60}h {minutes%60:02d}m'


def map_eta(state,job,x,y):
    return (f'<text class="map-staff map-eta" id="map-eta-{job["job_id"]}" '
            f'x="{x}" y="{y}" text-anchor="middle" font-size=".32" pointer-events="none">'
            f'ETA {job_eta(state,job)}</text>')


def derelict_salvage_label(state, site):
    """Public range estimate; never reveal the site's persisted private roll."""
    if site['status']=='cleared':
        return 'No salvage remaining'
    from game.support import best
    job=next((j for j in state.get('jobs',[]) if j['target_derelict_id']==site['settlement_derelict_id']
              and j['job_type']=='scavenging' and j['status'] in ('active','paused')),None)
    fraction=max(0,min(1,1-job['work_completed']/job['work_required'])) if job else 1
    bonus=max(0,best(state,'salvage_bonus'))/100
    loot=state['config']['derelicts'][site['derelict_type']]['loot']
    parts=[]
    for resource in ('food','water','scrap','metal','electronics'):
        low,high=loot.get(resource,(0,0))
        factor=fraction*(1+bonus if resource in ('scrap','metal','electronics') else 1)
        if high*factor<=0: continue
        low,high=round(low*factor,1),round(high*factor,1)
        amount=f'{low:g}–{high:g}' if low!=high else f'{high:g}'
        parts.append(f'{amount} {resource.title()}')
    return ' · '.join(parts) or 'No salvage remaining'


def scavenging_summary(state, include_completed=False):
    """Recovery includes overflow; display gross rate rather than retained stock."""
    from game.support import best
    result=[]
    for job in state['jobs']:
        if job['job_type']!='scavenging' or job['status'] not in (('active','paused','completed') if include_completed else ('active','paused')): continue
        site=next(d for d in state['derelicts'] if d['settlement_derelict_id']==job['target_derelict_id'])
        speed=0 if job['status']=='completed' else job_speed(state,job)
        running=state['season']['status'] in ('active','finalizing') and state['settlement']['status']=='active'
        totals=json.loads(site['random_result']);recovered=json.loads(site['recovered_loot'])
        bonus=best(state,'salvage_bonus')/100
        rates={r:totals.get(r,0)*speed/job['work_required']*3600*
               (1+bonus if r in ('scrap','metal','electronics') else 1) if running else 0
               for r in ('food','water','scrap','metal','electronics')}
        result.append(dict(job_id=job['job_id'],site_id=site['settlement_derelict_id'],
                           name=state['config']['derelicts'][site['derelict_type']]['name'],
                           workers=map_staff(state,derelict=site['settlement_derelict_id']),
                           percent=min(100,100*job['work_completed']/job['work_required']),
                           eta=job_eta(state,job,speed),
                           rates=rates,recovered=recovered,remaining_salvage=derelict_salvage_label(state,site)))
    return result


def resource_summary(values, hourly=False):
    shown=' · '.join(f'{v:.1f} {r.title()}{"/h" if hourly else ""}' for r,v in values.items() if v>0)
    return shown or ('No current yield' if hourly else 'Nothing recovered yet')


def live_payload(state):
    # Signal panel changes, never on each work-progress tick.
    structure = [[(b['building_id'], b['level'], b['status']) for b in state['buildings']],
                 [(c['citizen_id'], c['assignment_id'],c.get('away',False)) for c in state['citizens']],
                 [(j['job_id'], j['status'] == 'completed') for j in state['jobs']],
                 [(d['settlement_derelict_id'],d['status']) for d in state['derelicts']]]
    structure.append([state.get('needs_clock') is not None,(state.get('needs_clock') or {}).get('since'),state.get('policies'),[(u['unit_id'],u['status'],u['current_hp']) for u in state.get('units',[])],state.get('inventory',[])])
    structure.append([(j['job_id'],j['status'],j['repeat_production'],json.loads(j['inputs_spent']).get('produced',0)) for j in state['jobs'] if j['job_type']=='manufacturing'])
    if 'maintenance' in state['config']:structure.append(state.get('repair_drone_orders',{}))
    if expanded(state):
        structure.append([(bid,s['reason']) for bid,s in operating_status(state).items()])
    if state['season']['config_version'] in ('prototype_v5','prototype_v6','prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
        from game.population import housing
        structure.append([(cid,h['building_id'] if h else None) for cid,h in housing(state)['assignments'].items()])
    if state['season']['config_version'] in ('prototype_v6','prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
        structure.append([(c['citizen_id'],round(c['current_hp'],1),c['effective_morale']) for c in state['citizens']])
    if state['season']['config_version'] in ('prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
        structure.append([(c['citizen_id'],c['level'],round(c['xp'],2)) for c in state['citizens']])
    if state['season']['config_version'] in ('prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
        structure.append([(b['building_id'],round(b['current_hp'],2)) for b in state['buildings']])
    revision = hashlib.sha256(json.dumps(structure).encode()).hexdigest()[:16]
    jobs = {}
    for j in state['jobs']:
        if j['status'] not in ('active', 'paused'):
            continue
        speed = job_speed(state, j)
        percent = 100 * j['work_completed'] / j['work_required']
        detail = f'{percent:.1f}% complete · '
        if state['season']['status'] == 'paused':
            detail += 'Time is paused'
        elif not speed:
            detail += (j['pause_reason'] or 'Waiting for manufacturing inputs') if j['job_type']=='manufacturing' else 'Waiting for effective builders and Oxygen coverage'
        else:
            detail += f"{(j['work_required'] - j['work_completed']) / speed / 60:.1f} minutes remaining"
        jobs[str(j['job_id'])] = {'percent': percent, 'label': detail, 'eta':job_eta(state,j,speed)}
    return {'revision': revision, 'jobs': jobs}


def cost_label(s):
    return ' · '.join(f'{s[r]:g} {r.title()}' for r in ('scrap', 'metal', 'electronics') if s[r])


def form(token, action, body, **fields):
    hidden = {'token': token, 'action': action, **fields}
    return '<form method="post" action="/buildings">' + ''.join(
        f'<input type="hidden" name="{key}" value="{escape(str(value), quote=True)}">' for key, value in hidden.items()) + body + '</form>'


def benefits(s,info):
    labels={'food':'Food/hour','water':'Water/hour','scrap_output':'Scrap/hour','metal_output':'Metal/hour','electronics_output':'Electronics/hour',
            'food_storage':'Food storage','water_storage':'Water storage','material_storage':'Material storage',
            'electricity_output':'Electricity capacity','oxygen_output':'Oxygen capacity','housing':'housing places'}
    labels.update(drone_capacity='drone slots',repair_drone_capacity='repair drone slots',munition_capacity='munition slots',production_bonus='% manufacturing speed bonus',healing_bonus='% healing bonus',treatment_capacity='treatment places',construction_bonus='% construction/repair bonus',scavenge_bonus='% scavenging speed bonus',salvage_bonus='% material yield bonus',market_fee_reduction='% market fee reduction',morale='community morale',defense_radius='tile defense radius',defense_strength='post defense strength')
    parts=[f'{s.get(k,0):g} {label}' for k,label in labels.items() if s.get(k,0)]
    if s.get('radius'):parts.append(f'{s["radius"]:g}-tile radius')
    for r in ('scrap','metal'):
        if s.get(r+'_input'):parts.append(f'Uses {s[r+"_input"]:g} {r.title()}/hour')
    return ' · '.join(parts) or 'Utility infrastructure'


def current_output(status,s,info):
    if 'outputs' not in status:return f'+{status["output"]:g} Food/hour'
    parts=[f'+{value:g} {resource.title()}/hour' for resource,value in status['outputs'].items()]
    parts += [f'Uses {value:g} {resource.title()}/hour' for resource,value in status['inputs'].items()]
    if not parts and (s['oxygen_output'] or s['electricity_output']):
        for r in ('oxygen','electricity'):
            if s[r+'_output']:parts.append(f'{0 if status["reason"] else s[r+"_output"]*status["factor"]:g} {r.title()} capacity')
    if info.get('category')=='Housing':
        return 'Unusable housing' if status['reason'] else f"{int(s['housing']*status['factor']+1e-9)} housing places"
    return ' · '.join(parts) or ('Inactive' if status['reason'] else 'Storage available')


def scavenging_panel(state,token):
    from game.scavenging import safe_coverage
    from game.economy import storage,utilities
    store=storage(state);u=utilities(state)
    result='<section class="production-panel" id="scavenging"><div class="panel-heading"><div><p class="eyebrow">RECOVER THE OLD WORLD</p><h2>Scavenging &amp; capacity</h2></div></div><div class="building-controls">'
    result+=f'<p>Storage: {store["food"]:g} Food · {store["water"]:g} Water · {store["material"]:g} shared materials.</p>'
    result+=''.join(f'<p>{name.title()} capacity: {u["used"][name]:g} used / {u["capacity"][name]:g} generated.</p>' for name in ('oxygen','electricity'))
    result+='</div><h3>Active scavenging</h3><p class="small-note">Current gross yield and recovery before storage limits. Overflow is discarded; ETA assumes current crew and conditions.</p><div class="work-cards">'
    summary=scavenging_summary(state)
    for row in summary:
        jid=row['job_id']
        result+=f'<article class="work-card"><h4><a href="#derelict-{row["site_id"]}">{escape(row["name"])} #{row["site_id"]}</a></h4><p><span id="scavenge-workers-{jid}">{row["workers"]}</span> people · <span id="scavenge-percent-{jid}">{row["percent"]:.0f}% recovered</span> · ETA <strong id="scavenge-eta-{jid}">{row["eta"]}</strong></p><progress id="scavenge-progress-{jid}" max="100" value="{row["percent"]}" aria-label="Scavenging recovery"></progress><dl><dt>Current yield</dt><dd id="scavenge-yield-{jid}">{resource_summary(row["rates"],True)}</dd><dt>Recovered so far</dt><dd id="scavenge-recovered-{jid}">{resource_summary(row["recovered"])}</dd></dl></article>'
    if not summary: result+='<p>No active scavenging. Open a site below to assign a crew.</p>'
    result+='</div><details class="player-info"><summary>Choose a scavenging site / manage crews</summary><div class="ruin-list">'
    jobs=live_payload(state)['jobs']
    frozen=state['season']['status']=='finished' or state['settlement']['status']!='active'
    free=[c for c in state['citizens'] if c['assignment']=='unassigned' and c['current_hp']>0 and not c.get('away')]
    for d in sorted(state['derelicts'],key=lambda d:(d['status']=='cleared',-safe_coverage(state,d),d['settlement_derelict_id'])):
        did=d['settlement_derelict_id'];info=state['config']['derelicts'][d['derelict_type']]
        safe=safe_coverage(state,d)>=state['config']['construction']['coverage_fraction']
        job=next((j for j in state['jobs'] if j['target_derelict_id']==did and j['status'] in ('active','paused')),None)
        result+=f'<details id="derelict-{did}"><summary>{info["name"]} #{did} · ({d["origin_x"]}, {d["origin_y"]}) · {"Cleared" if d["status"]=="cleared" else "Safe Oxygen coverage" if safe else "Needs Oxygen coverage"}</summary>'
        result+=f'<p><strong>Estimated remaining salvage</strong><br><span id="derelict-salvage-{did}">{escape(derelict_salvage_label(state,d))}</span></p>'
        if d['status']!='cleared':
            result+='<p class="small-note">Possible quantities, including current salvage bonuses. Actual finds vary; bonuses may change. Supplies arrive gradually and overflow is discarded.</p>'
            result+=f'<p>{info["minutes"]:g} minutes with one normal scavenger. Up to {info["workers"]} workers.</p>'
            if job:
                shown=jobs[str(job['job_id'])]
                result+=f'<progress id="progress-{job["job_id"]}" value="{shown["percent"]}" max="100" aria-label="Scavenging progress"></progress><p id="job-{job["job_id"]}">{shown["label"]}</p>'
            choices=''.join(f'<option value="{c["citizen_id"]}">{escape(c["name"])}</option>' for c in free)
            disabled=' disabled' if frozen or (not safe and 'consequences' not in state['config']) or not free else ''
            warning='<label><input type="checkbox" name="exposed" value="1" required>Danger: outside Oxygen. Rapid HP loss and emergency evacuation at 25% HP.</label>' if not safe and 'consequences' in state['config'] else ''
            result+=f'<form method="post" action="/scavenging"><input type="hidden" name="token" value="{escape(token,quote=True)}"><input type="hidden" name="action" value="assign"><input type="hidden" name="derelict_id" value="{did}"><label for="scavenger-{did}">Scavenger for {info["name"]} #{did}</label><select id="scavenger-{did}" name="citizen_id">{choices or "<option>No unassigned citizens</option>"}</select>{warning}<button{disabled}>Assign scavenger</button></form>'
            for citizen in state['citizens']:
                if job and citizen['job_id']==job['job_id']:
                    result+=f'<form method="post" action="/scavenging"><input type="hidden" name="token" value="{escape(token,quote=True)}"><input type="hidden" name="action" value="release"><input type="hidden" name="derelict_id" value="{did}"><input type="hidden" name="citizen_id" value="{citizen["citizen_id"]}"><button{" disabled" if frozen else ""}>Release {escape(citizen["name"])}</button></form>'
        result+='</details>'
    return result+'</div></details></section>'


def build_availability(state, info):
    """Use spendable stock, including trade reservations, for display only."""
    from game.trading import available
    shortages = {r: max(0, info['levels'][0][r] - available(state, r))
                 for r in ('scrap', 'metal', 'electronics')}
    reasons = []
    if state['buildings'][0]['level'] < info['unlock']:
        reasons.append(f"Town Hall {info['unlock']} required")
    reasons += [f"Need {amount:g} more {r.title()}" for r, amount in shortages.items() if amount > 0]
    return reasons


def map_staff(state, building=None, derelict=None):
    """Count physically present assigned citizens, not drone inventory or raiders."""
    jobs = {j['job_id'] for j in state['jobs']
            if j['status'] in ('active', 'paused') and
            ((building is not None and j['target_building_id'] == building) or
             (derelict is not None and j['target_derelict_id'] == derelict))}
    return sum(1 for c in state['citizens'] if not c.get('away') and
               ((building is not None and c['building_id'] == building) or
                c['job_id'] in jobs))


def staffing_hint(state, building, worker_slots):
    """A missing crew differs from missing production staff or passive housing."""
    job=next((j for j in state['jobs'] if j['target_building_id']==building['building_id']
              and j['job_type'] in ('construction','upgrade','repair')
              and j['status'] in ('active','paused')),None)
    if job:
        staffed=any(c['job_id']==job['job_id'] and not c.get('away') for c in state['citizens'])
        return {'unstaffed':not staffed,'label':'Needs repair crew' if job['job_type']=='repair' else 'Needs builders'}
    if building['status']=='active' and worker_slots>0:
        staffed=any(c['building_id']==building['building_id'] and
                    c['assignment'] in ('production','defender') and not c.get('away')
                    for c in state['citizens'])
        return {'unstaffed':not staffed,'label':'Unstaffed'}
    return {'unstaffed':False,'label':''}


def staffing_payload(state):
    return {str(b['building_id']):staffing_hint(state,b,spec(state,b)['workers'])
            for b in state['buildings'] if b['building_type']!='town_hall'
            and b['status'] in ('active','construction','upgrading')}


def map_filter_flags(state):
    flags={}
    running=state['season']['status'] in ('active','finalizing') and state['settlement']['status']=='active'
    blocked={j['job_id'] for j in state['jobs'] if j['status'] in ('active','paused') and
             j['work_completed']<j['work_required'] and running and job_speed(state,j)<=0}
    for b in state['buildings']:
        if b['status'] in ('cleared','demolished'):continue
        key='town-hall' if b['building_type']=='town_hall' else ('ruin-' if b['status']=='ruined' else 'building-')+str(b['building_id'])
        definition=spec(state,b)
        flags[key]=dict(unstaffed=staffing_hint(state,b,definition['workers'])['unstaffed'],
                        stalled=any(j['target_building_id']==b['building_id'] and j['job_id'] in blocked for j in state['jobs']),
                        damaged=b['status'] in ('active','upgrading','ruined') and b['current_hp']<definition['hp'])
    for d in state['derelicts']:
        if d['status']=='cleared':continue
        flags['derelict-'+str(d['settlement_derelict_id'])]=dict(unstaffed=False,damaged=False,
            stalled=any(j['target_derelict_id']==d['settlement_derelict_id'] and j['job_id'] in blocked for j in state['jobs']))
    return flags


def filter_attributes(key, flags):
    return f'data-map-key="{key}" '+ ' '.join(f'data-{k}="{int(v)}"' for k,v in flags[key].items())


def map_requires_staff(state, building, worker_slots):
    """Passive buildings still need crews for construction, repair or salvage."""
    if building['building_type']=='town_hall': return True
    if building['status'] in ('construction','upgrading'): return True
    if any(j['target_building_id']==building['building_id'] and
           j['job_type'] in ('construction','upgrade','repair','building_salvage') and
           j['status'] in ('active','paused') for j in state['jobs']): return True
    return building['status']=='active' and worker_slots>0


def staff_badge(count, x, y):
    # A tiny vector person and numeric count avoid font/emoji dependencies.
    return (f'<g class="map-people" pointer-events="none"><title>{count} assigned citizens</title>'
            f'<circle cx="{x-.23}" cy="{y-.22}" r=".075" fill="#fff4d8"/>'
            f'<path d="M {x-.23} {y-.13} v .16 m -.1 -.1 h .2 m -.1 .1 l -.08 .1 m .08 -.1 l .08 .1" '
            'fill="none" stroke="#fff4d8" stroke-width=".055"/>'
            f'<text class="map-staff" x="{x+.08}" y="{y}" text-anchor="middle" font-size=".4">{count}</text></g>')


def map_occupancy(state):
    """Full current footprints, including ruins, for client placement hints."""
    return [dict(x=b['origin_x'],y=b['origin_y'],
                 width=footprint(state,b)[0],height=footprint(state,b)[1])
            for b in state['buildings'] if b['status'] not in ('cleared','demolished')] + [
           dict(x=d['origin_x'],y=d['origin_y'],
                width=state['config']['derelicts'][d['derelict_type']]['footprint'][0],
                height=state['config']['derelicts'][d['derelict_type']]['footprint'][1])
           for d in state['derelicts'] if d['status']!='cleared']


def scavenging_badge(state, derelict, x, y, width, height=1):
    """Remaining-work fraction tracks gradual recovery, not stored salvage."""
    job = next((j for j in state['jobs'] if j['target_derelict_id']==derelict and
                j['job_type']=='scavenging' and j['status'] in ('active','paused')), None)
    if not job: return ''
    recovered = min(100,max(0,100*job['work_completed']/job['work_required']))
    length = max(.4,width-.75)
    return (f'<g class="map-scavenging" id="map-scavenging-{job["job_id"]}" '
            f'aria-label="Scavenging: {recovered:.0f}% recovered">'
            f'<title>Scavenging: {recovered:.0f}% recovered</title>'
            f'<path class="scavenge-pickaxe" d="M {x+.12} {y+.1} l .27 .27 '
            f'M {x+.07} {y+.23} q .14 -.23 .35 -.16" fill="none" stroke="#d5a553" stroke-width=".065"/>'
            f'<path d="M {x+.5} {y+.22} h {length}" stroke="#302a20" stroke-width=".12"/>'
            f'<path class="scavenge-remaining" data-length="{length}" '
            f'd="M {x+.5} {y+.22} h {length}" pathLength="100" stroke="#d5a553" '
            f'stroke-width=".12" stroke-dasharray="{100-recovered:g} 100" fill="none"/></g>' + (map_eta(state,job,x+width/2,y+height+.27) if "season" in state else ""))


def map_job_badge(state, building, x, y, height=1):
    job = next((j for j in state['jobs'] if j['target_building_id']==building and
                j['job_type'] in ('construction','upgrade','repair') and
                j['status'] in ('active','paused')), None)
    if not job: return ''
    percent = min(100, max(0, 100*job['work_completed']/job['work_required']))
    return (f'<text class="map-staff map-job" id="map-job-{job["job_id"]}" '
            f'x="{x}" y="{y}" text-anchor="middle" font-size=".4" pointer-events="none">'
            f'<title>{escape(job["job_type"].title())} progress</title>{percent:.0f}%</text>' + (map_eta(state,job,x,y+height-.23) if "season" in state else ""))




def panels(state, token):
    from game.trading import available
    catalog = rules(state)['buildings']
    wide=expanded(state)
    hall = state['buildings'][0]
    frozen = state['season']['status'] == 'finished' or state['settlement']['status'] != 'active'
    at = state['season']['paused_at'] if state['season']['status'] == 'paused' else state['settlement']['simulation_processed_at']
    finalizing = at >= state['season']['finalization_at'] or state['season']['status'] == 'finalizing'
    options, rows = [], []
    for kind, info in catalog.items():
        if kind == 'town_hall':
            continue
        s = info['levels'][0]
        reasons = build_availability(state, info)
        costs = ''.join(f' data-cost-{r}="{s[r]}"' for r in ('scrap','metal','electronics'))
        options.append(f'<option value="{kind}" data-width="{info["footprint"][0]}" data-height="{info["footprint"][1]}"'
                       + costs + f' data-name="{escape(info["name"],quote=True)}" data-unlock="{info["unlock"]}"'
                       + (' disabled' if reasons else '') + f'>{info["name"]}'
                       + (' — ' + '; '.join(reasons) if reasons else '') + '</option>')
        rows.append(f'<tr><th scope="row">{info["name"]}</th><td>{cost_label(s)}</td><td>{s["minutes"]:g} min</td>'
                    f'<td>{benefits(s,info)}</td><td>{info["max_level"]}</td><td>Town Hall {info["unlock"]}</td></tr>')
    no_choice = all(build_availability(state, info) for kind,info in catalog.items() if kind != 'town_hall')
    disabled = ' disabled' if frozen or finalizing or no_choice else ''
    if no_choice: options.insert(0, '<option value="" selected disabled>No buildings available — see requirements below</option>')
    build = form(token, 'build', '<div class="build-fields"><div><label for="building-type">Building</label>'
                 f'<select id="building-type" name="building_type" data-hall-level="{hall["level"]}" data-build-locked="{int(frozen or finalizing)}" ' + ''.join(f'data-available-{r}="{available(state,r)}" ' for r in ('scrap','metal','electronics')) + '>' + ''.join(options) + '</select></div>'
                 '<div><label for="build-x">Map column (0–39)</label><input id="build-x" name="x" type="number" min="0" max="39" required value="21"></div>'
                 '<div><label for="build-y">Map row (0–39)</label><input id="build-y" name="y" type="number" min="0" max="39" required value="18"></div>'
                 '<div><label for="build-rotation">Orientation</label><select id="build-rotation" name="rotation"><option value="0">Normal</option><option value="90">Rotated 90°</option></select></div></div>'
                 f'<button type="submit"{disabled}>Start construction</button>')
    placement = '<section class="production-panel" id="construction"><div class="panel-heading"><div><p class="eyebrow">GROW YOUR SETTLEMENT</p><h2>Build a building</h2></div></div>'
    placement += '<div class="table-scroll"><table><caption class="sr-only">Building catalog</caption><thead><tr><th>Building</th><th>Materials</th><th>One builder</th><th>Benefits</th><th>Max level</th><th>Unlock</th></tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>'
    requirements = ''.join('<li>'+escape(info['name'])+': '+escape('; '.join(build_availability(state,info)))+' '+material_market_link(state,info['levels'][0])+'</li>' for kind,info in catalog.items() if kind != 'town_hall' and build_availability(state,info))
    placement += '<details class="player-info"><summary>Unavailable buildings: missing materials &amp; unlocks</summary><ul id="build-requirements">'+requirements+'</ul></details>'
    placement += '<div class="building-controls"><p>Select a map tile or enter its column and row. The outlined footprint is a preview; occupied tiles are rejected. Costs are paid when construction starts.</p>' + build
    placement += '<p class="small-note">Assign builders after placing the site, then Start time. Builders become unassigned when work finishes; assign Food workers separately. Gardens have one level. Greenhouses and Hydroponics each have three.</p>'
    if finalizing:
        placement += '<p class="error">Construction and upgrades are closed during the final three hours.</p>'
    placement += '</div></section>'
    operating = operating_status(state)
    jobs_display = live_payload(state)['jobs']
    hall_controls, food_cards = '', []
    for b in state['buildings']:
        if b['status'] in ('demolished','cleared'):continue
        if b['status'] not in ('active', 'construction', 'upgrading'):
            continue
        bid = b['building_id']
        info, s = catalog[b['building_type']], spec(state, b)
        job = next((j for j in state['jobs'] if j['target_building_id'] == bid and j['job_type']!='manufacturing' and j['status'] in ('active', 'paused')), None)
        controls = ''
        if job:
            shown = jobs_display[str(job['job_id'])]
            target = b['level'] + (job['job_type'] == 'upgrade')
            controls += f'<p><strong>{"Repairing" if job["job_type"] == "repair" else "Upgrading to" if job["job_type"] == "upgrade" else "Building"} level {target}</strong></p>'
            controls += f'<progress id="progress-{job["job_id"]}" max="100" value="{shown["percent"]}" aria-label="Construction progress"></progress><p id="job-{job["job_id"]}">{shown["label"]}</p>'
        elif b['level'] < info['max_level']:
            target = spec(state, b, b['level'] + 1)
            affordable = all(available(state,r) >= target[r] for r in ('scrap', 'metal', 'electronics'))
            controls += f'<p><strong>Upgrade to level {b["level"] + 1}</strong><br>{cost_label(target)} · {target["minutes"]:g} minutes with one builder.</p>'
            controls += f'<p class="small-note">{benefits(target,info)} · Worker slots: {target["workers"]:g}.'
            if b['building_type'] == 'town_hall':
                controls += f' Water: {target["water"]:g}/hour · Housing: {target["housing"]:g}. Unlocks {"Greenhouses" if b["level"] == 1 else "Hydroponics"}.'
            controls += '</p>'
            upgrade_disabled = ' disabled' if frozen or finalizing or not affordable else ''
            controls += form(token, 'upgrade', f'<button type="submit"{upgrade_disabled}>Upgrade {info["name"]}</button>', building_id=bid, expected_level=b['level'])
            if not affordable:
                controls += '<p class="small-note">'+material_market_link(state,target)+'</p>'
        else:
            controls += '<p class="small-note">Maximum level reached.</p>'
        if state['season']['config_version'] in ('prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13') and not job and b['status']=='active' and 0<b['current_hp']<s['hp'] and b['building_type'] not in ('pup_tent','upgraded_tent'):
            from game.repairs import costs
            price=costs(state,b)
            affordable=all(available(state,r)>=value for r,value in price.items())
            controls+=f'<p>Repair materials: {cost_label(price) or "Free"}. 20 HP/hour with one normal worker.</p>'
            controls+=form(token,'repair',f'<button{" disabled" if frozen or finalizing or not affordable else ""}>Start repairs</button>',building_id=bid)
        if 'maintenance' in state['config']:
            from game.building_management import refund,recovery
            if job and job['job_type'] in ('construction','upgrade'):
                controls+=form(token,'cancel_build',f'<p>Cancel this project: recover {cost_label(refund(state,job))}. Recovery above free material storage is discarded.</p><button class="secondary"{" disabled" if frozen else ""}>Cancel project #{bid}</button>',building_id=bid)
            elif not job and b['status']=='active' and b['building_type']!='town_hall':
                controls+=form(token,'demolish',f'<p>Demolish permanently: recover {cost_label(recovery(state,b))}. Recovery above free material storage is discarded. Workers are released and residents reassigned.</p><label><input type="checkbox" required> Confirm permanent demolition</label><button class="secondary"{" disabled" if frozen else ""}>Demolish building #{bid}</button>',building_id=bid)
        free = [c for c in state['citizens'] if c['assignment'] == 'unassigned' and c['current_hp'] > 0 and not c.get('away')]
        # Current Administrators can move directly to ordinary production/building work.
        admin_movable=state['season']['config_version']=='prototype_v13' and (not job or job['job_type'] in ('construction','upgrade')) and b['building_type']!='guard_post'
        if admin_movable:free += [c for c in state['citizens'] if c['assignment']=='administrator' and c['current_hp']>0 and not c.get('away')]
        can_assign = not frozen and bool(free)
        action = ('repairer' if job['job_type']=='repair' else 'builder') if job else 'worker'
        if not job and b['building_type']=='guard_post':action='guard'
        if job or (b['building_type'] != 'town_hall' and s['workers']):
            label = ('Repair worker' if job['job_type']=='repair' else 'Builder') if job else 'Food worker' if info.get('category','Food')=='Food' else 'Guard' if b['building_type']=='guard_post' else 'Production worker'
            select_id = f'worker-{bid}'
            choices = ''.join(f'<option value="{c["citizen_id"]}">{escape(c["name"])}</option>' for c in free) or '<option>No unassigned citizens</option>'
            if not job and operating[bid]['workers'] >= s['workers']:
                can_assign = False
            warning='<label><input type="checkbox" name="exposed" value="1" required>Danger: outside Oxygen. Rapid HP loss and emergency evacuation at 25% HP.</label>' if 'consequences' in state['config'] and b['building_type']!='town_hall' and coverage(state,b)<state['config']['construction']['coverage_fraction'] else ''
            controls += form(token, action, warning+f'<label for="{select_id}">{label} for {info["name"]} #{bid}</label><select id="{select_id}" name="citizen_id">{choices}</select>'
                             f'<button type="submit"{"" if can_assign else " disabled"}>Assign {label.lower()}</button>', building_id=bid)
        for c in state['citizens']:
            if c['building_id'] == bid and c['assignment'] in ('production', 'construction','repair'):
                controls += form(token, 'release', f'<span>{escape(c["name"])} · {"Builder" if c["assignment"] == "construction" else "Repair worker" if c["assignment"] == "repair" else "Production worker"}</span>'
                                 f'<button type="submit" class="secondary"{" disabled" if frozen else ""}>Release {escape(c["name"])}</button>', building_id=bid, citizen_id=c['citizen_id'])
        if b['building_type'] == 'town_hall':
            hall_controls = '<div class="building-controls">' + controls + '</div>'
        else:
            status = operating[bid]
            hint=staffing_hint(state,b,s['workers'])
            card_class='food-card unstaffed-building' if hint['unstaffed'] else 'food-card'
            staff_hidden='' if hint['unstaffed'] else ' hidden'
            w, h = footprint(state, b)
            food_cards.append(f'<article class="{card_class}" id="building-{bid}"><p class="staffing-warning" id="staffing-warning-{bid}"{staff_hidden}>{hint["label"]} · open staffing controls below</p><h3>{info["name"]} #{bid} <span class="tag">LEVEL {b["level"]}</span></h3>'
                f'<p>{w} × {h} tiles at ({b["origin_x"]}, {b["origin_y"]}) · {b["current_hp"]:g}/{s["hp"]:g} HP</p>'
                f'<p><strong>{current_output(status,s,info)}</strong> · {status["workers"]}/{s["workers"]:g} workers</p>'
                f'<p>{escape(status["reason"] or "Operating when time runs")}. Utility coverage: {coverage(state,b)*100:.0f}%.</p>'
                f'<p class="small-note">{benefits(s,info)}. Electricity demand: {s["electricity_demand"]:g}; Oxygen demand: {s["oxygen_demand"]:g}.</p>'
                '<div class="building-controls">' + controls + '</div></article>')
    cards = '<section class="food-section" aria-label="Food buildings"><h2>Food buildings</h2><div class="food-cards">' + (''.join(food_cards) or '<p>No Food buildings yet. Start with a Garden beside the Town Hall.</p>') + '</div></section>'
    if wide:
        placement=placement.replace('Food building','Production building').replace('Food output','Output / capacity').replace('GROW YOUR FOOD SUPPLY','BUILD YOUR ECONOMY')
        cards=cards.replace('Food buildings','Production buildings')
        hall_controls=hall_controls.replace('Enable civilian production to scavenge supplies.','Scavenge supplies or produce more materials.')
        cards=cards.replace('Enable civilian production to scavenge supplies.','Scavenge supplies or produce more materials.')
        placement += scavenging_panel(state,token)
    else:
        placement=form(token,'enable','<p>Enable the civilian economy to unlock Water, utilities, material converters, storage, and scavenging. Existing buildings and supplies are retained.</p><button>Enable civilian production</button>')+placement
    if state['season']['config_version'] not in ('prototype_v5','prototype_v6','prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
        placement=form(token,'enable_housing','<p>Add housing and rare survivor discoveries to the civilian economy. Existing supplies and scavenging progress are retained.</p><button>Enable housing and survivors</button>')+placement
    else:
        placement=placement.replace('Production building','Settlement building').replace('assign Food workers separately. Gardens have one level. Greenhouses and Hydroponics each have three.','assign production workers separately. Housing needs no production workers.')
        placement+='<p class="small-note">Survivors may join during scavenging. They need Food, Water, and safe housing; housing full means homelessness, rather than rejecting the survivor. Births and ongoing health/morale effects remain deferred.</p>'
    if state['season']['config_version'] not in ('prototype_v6','prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
        placement=form(token,'enable_recovery','<p>Add natural citizen recovery and housing morale effects. Existing health and base morale are retained.</p><button>Enable citizen recovery</button>')+placement
    else:
        placement=placement.replace('Births and ongoing health/morale effects remain deferred.','Natural recovery and housing morale are active. Births and ongoing homelessness damage remain deferred.')
    if state['season']['config_version'] not in ('prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
        placement=form(token,'enable_progression','<p>Citizens earn XP from productive work and level automatically.</p><button>Enable citizen progression</button>')+placement
    if state['season']['config_version'] not in ('prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
        placement=form(token,'enable_repairs','<p>Add repair crews and slow staffed Town Hall regeneration.</p><button>Enable building repairs</button>')+placement
    return placement, hall_controls, cards



MAP_PURPOSES={
    'Food':('Food','#7fae74','F'), 'Water':('Water','#77a9cd','W'),
    'Oxygen':('Oxygen','#63b6ac','O'), 'Electricity':('Electricity','#d6b55f','E'),
    'Industry':('Industry','#c89361','I'), 'Housing':('Housing','#c8bca2','H'),
    'Drones':('Military','#b37b79','M'), 'Munitions':('Military','#b37b79','M'),
    'Defense':('Military','#b37b79','M'), 'Storage':('Storage','#9f8ab8','S'),
    'Support':('Support','#9ba8b4','+')}


def map_purpose(info):
    """Primary purpose only; secondary output and work status do not change it."""
    category=info.get('category','Support')
    if category in ('Food Storage','Water Storage','Material Storage'):category='Storage'
    return MAP_PURPOSES.get(category,MAP_PURPOSES['Support'])


def map_additions(state):
    flags=map_filter_flags(state)
    hall = state['buildings'][0]
    radius = spec(state, hall)['radius']
    # Rounded rectangle is the footprint-distance boundary used by coverage().
    overlay = f'<rect class="utility-zone" x="{hall["origin_x"]-radius}" y="{hall["origin_y"]-radius}" width="{3+2*radius}" height="{3+2*radius}" rx="{radius}" fill="none" stroke="#95b69b" stroke-width=".1" stroke-dasharray=".3 .2"/>'
    if expanded(state):
        from game.economy import utilities
        for utility,zones in utilities(state)['zones'].items():
            for b in zones[1:]:
                w,h=footprint(state,b);r=spec(state,b)['radius']
                color='#95b69b' if utility=='oxygen' else '#cfba6f'
                overlay+=f'<rect data-utility="{utility}" x="{b["origin_x"]-r}" y="{b["origin_y"]-r}" width="{w+2*r}" height="{h+2*r}" rx="{r}" fill="none" stroke="{color}" stroke-width=".1" stroke-dasharray=".3 .2"/>'
        for d in state['derelicts']:
            if d['status']=='cleared':continue
            w,h=state['config']['derelicts'][d['derelict_type']]['footprint'];did=d['settlement_derelict_id']
            count=map_staff(state,derelict=did)
            overlay+=f'<a {filter_attributes("derelict-"+str(did),flags)} href="#derelict-{did}" aria-label="Inspect derelict #{did}"><rect x="{d["origin_x"]}" y="{d["origin_y"]}" width="{w}" height="{h}" class="map-derelict" fill="#65574e" stroke="#a49b87" stroke-dasharray=".22 .14" stroke-width=".1"/><text x="{d["origin_x"]+w/2}" y="{d["origin_y"]+h/2+.2}" text-anchor="middle" fill="#eee" font-size=".55">R{did}</text>{scavenging_badge(state,did,d["origin_x"],d["origin_y"],w,h)}{staff_badge(count,d["origin_x"]+w/2,d["origin_y"]+h-.2)}<title>{escape(state["config"]["derelicts"][d["derelict_type"]]["name"])}: {count} assigned scavengers</title></a>'
    for b in state['buildings'][1:]:
        if b['status'] in ('cleared', 'demolished'):
            continue
        w, h = footprint(state, b)
        purpose,color,symbol=map_purpose(rules(state)['buildings'][b['building_type']])
        shape_class='map-derelict' if b['status']=='ruined' else 'map-construction' if b['status'] in ('construction','upgrading') else 'map-complete'
        if b['status']=='ruined':color='#65574e'
        name = rules(state)['buildings'][b['building_type']]['name']
        if b['building_type'] in ('guard_post','automated_turret','anti_air_turret') and b['status']=='active':
            r=spec(state,b)['defense_radius']
            overlay+=f'<rect x="{b["origin_x"]-r}" y="{b["origin_y"]-r}" width="{w+2*r}" height="{h+2*r}" rx="{r}" fill="none" stroke="#cd8f82" stroke-width=".12" stroke-dasharray=".3 .2"><title>{escape(name)} defense radius</title></rect>'
        count=map_staff(state,building=b['building_id'])
        show_staff=map_requires_staff(state,b,spec(state,b)['workers'])
        marker=staff_badge(count,b['origin_x']+w/2,b['origin_y']+h-.2) if show_staff else ''
        staff_description=f'{count} assigned citizens' if show_staff else 'No operating staff required'
        anchor='ruin' if b['status']=='ruined' else 'building'
        overlay += f'<a {filter_attributes(anchor+"-"+str(b["building_id"]),flags)} href="#{anchor}-{b["building_id"]}" aria-label="Inspect {name} #{b["building_id"]}" data-purpose="{purpose}"><rect class="{shape_class}" x="{b["origin_x"]}" y="{b["origin_y"]}" width="{w}" height="{h}" fill="{color}" stroke="#e0d7b9" stroke-width=".12"/><text x="{b["origin_x"]+w/2}" y="{b["origin_y"]+h/2+.2}" text-anchor="middle" font-size=".65" fill="#111">{b["building_id"]} L{b["level"]}</text>{map_job_badge(state,b["building_id"],b["origin_x"]+w/2,b["origin_y"]+.5,h)}{marker}<text x="{b["origin_x"]+.12}" y="{b["origin_y"]+.3}" font-size=".26" fill="#182019" pointer-events="none">{symbol}</text><title>{name}, {purpose}, level {b["level"]}, {b["status"]}, {staff_description}</title></a>'
    overlay += '<rect id="placement-preview" x="21" y="18" width="2" height="2" fill="#d5bc7a" fill-opacity=".18" stroke="#ecd79f" stroke-width=".14" pointer-events="none"/>'
    return overlay

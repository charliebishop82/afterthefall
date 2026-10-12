"""Hostile building damage and private, progressively salvaged building ruins."""
import json, math
from html import escape
from game.buildings import spec,footprint,productivity,coverage,minimum_hp
from game.settlement import read_state,account_scope
from game.building_management import MATERIALS,credit


def invested(state,b):
    jobs=[j for j in state['jobs'] if j['target_building_id']==b['building_id'] and j['job_type'] in ('construction','upgrade') and j['status'] in ('completed','active','paused')]
    completed=[j for j in jobs if j['status']=='completed']
    # A seeded/legacy building may have upgrade records but no original build job.
    missing_levels=0 if b['status']=='construction' or any(j['job_type']=='construction' for j in completed) else b['level']-sum(j['job_type']=='upgrade' for j in completed)
    legacy=state['config']['buildings'][b['building_type']]['levels'][:missing_levels]
    base={r:sum(json.loads(j['inputs_spent']).get(r,0) for j in completed)+sum(s[r] for s in legacy) for r in MATERIALS}
    work=sum(j['work_required'] for j in completed)+sum(s['minutes']*60 for s in legacy)
    for j in jobs:
        if j['status']=='completed':continue
        fraction=min(1,j['work_completed']/j['work_required']);data=json.loads(j['inputs_spent'])
        for r in MATERIALS:base[r]+=data.get(r,0)*fraction
        work+=j['work_required']*fraction
    return base,max(1,work)


def release(connection,sid,bid,now):
    jobs=[r[0] for r in connection.execute("SELECT job_id FROM settlement_jobs WHERE settlement_id=? AND (target_building_id=? OR production_building_id=?) AND status IN ('queued','active','paused')",(sid,bid,bid))]
    for row in connection.execute("SELECT job_id,inputs_spent FROM settlement_jobs WHERE settlement_id=? AND job_type='manufacturing' AND status IN ('active','paused')",(sid,)).fetchall():
        data=json.loads(row['inputs_spent'])
        if data.get('paid') and data.get('home_id')==bid and row['job_id'] not in jobs:jobs.append(row['job_id'])
    for row in connection.execute("SELECT j.job_id FROM settlement_jobs j JOIN military_units u ON u.unit_id=j.target_unit_id WHERE j.settlement_id=? AND j.job_type='drone_repair' AND j.status IN ('active','paused') AND u.home_building_id=?",(sid,bid)).fetchall():
        if row['job_id'] not in jobs:jobs.append(row['job_id'])
    for jid in jobs:
        connection.execute("UPDATE citizens SET unemployed_since=? WHERE citizen_id IN (SELECT citizen_id FROM citizen_assignments WHERE job_id=? AND ended_at IS NULL)",(now,jid))
        connection.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='building_destroyed' WHERE job_id=? AND ended_at IS NULL",(now,jid))
        # A workshop's patient survives destruction of the workshop if housed elsewhere.
        connection.execute("UPDATE military_units SET status='available' WHERE status='repairing' AND unit_id IN (SELECT target_unit_id FROM settlement_jobs WHERE job_id=?)",(jid,))
        connection.execute("UPDATE settlement_jobs SET status='cancelled',pause_reason='Building destroyed',last_processed_at=? WHERE job_id=?",(now,jid))
    connection.execute("UPDATE citizens SET unemployed_since=? WHERE citizen_id IN (SELECT citizen_id FROM citizen_assignments WHERE building_id=? AND ended_at IS NULL)",(now,bid))
    connection.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='building_destroyed' WHERE building_id=? AND ended_at IS NULL",(now,bid))
    connection.execute("UPDATE military_units SET status='destroyed',current_hp=0,destroyed_at=? WHERE home_building_id=? AND status IN ('available','repairing')",(now,bid))
    away=[r[0] for r in connection.execute("SELECT unit_id FROM military_units WHERE home_building_id=? AND status='deployed' AND current_hp>0 ORDER BY unit_id",(bid,))]
    if away:
        from game.simulation import _event
        _event(connection,read_state(connection),'deployed_drone_home_destroyed',now,{'building_id':bid,'unit_ids':away})


def distance(state,a,b):
    aw,ah=footprint(state,a);bw,bh=footprint(state,b)
    dx=max(a['origin_x']-(b['origin_x']+bw),b['origin_x']-(a['origin_x']+aw),0)
    dy=max(a['origin_y']-(b['origin_y']+bh),b['origin_y']-(a['origin_y']+ah),0)
    return math.hypot(dx,dy)


def hit(connection,state,bid,damage,now,attack_id,report,exploded=None):
    """Apply one hit, then queued chain explosions; never hit one store twice per chain."""
    from game.consequences import die,replace_admin
    from game.population import housing,rebalance
    from game.combat import settings
    exploded=set() if exploded is None else exploded
    b=next((b for b in state['buildings'] if b['building_id']==bid),None)
    if not b or b['status'] not in ('active','construction','upgrading') or damage<=0:return
    before=b['current_hp'];maximum=spec(state,b)['hp']
    vault_loss=None
    if state.get('expansion') and b['building_type']=='vault' and damage>=before:
        from game.vaults import destroyed as destroy_vault
        vault_loss=destroy_vault(connection,state,bid,attack_id,now)
    tent=b['building_type'] in ('pup_tent','upgraded_tent')
    # Do not heal legacy saves whose Hall is already below the damage floor.
    after=min(before,max(minimum_hp(state,b),before-damage))
    if tent:after=0
    occupants={c['citizen_id']:c for c in state['citizens'] if not c.get('away') and c['building_id']==bid}
    for cid,home in housing(state)['assignments'].items():
        if home and home['building_id']==bid:
            c=next(c for c in state['citizens'] if c['citizen_id']==cid)
            if not c.get('away'):occupants[cid]=c
    injuries=[]
    for c in occupants.values():
        row=connection.execute('SELECT current_hp,status FROM citizens WHERE citizen_id=?',(c['citizen_id'],)).fetchone()
        if row['status']!='alive':continue
        hp=max(0,row['current_hp']-(before-after)/maximum*(state['config']['citizen_hp']+(c['level']-1)*state['config']['simulation']['hp_per_level'])*state['config']['structural']['occupant_injury_fraction'])
        connection.execute('UPDATE citizens SET current_hp=? WHERE citizen_id=?',(hp,c['citizen_id']))
        if hp<=0:die(connection,state,c,now,'structural_combat',attack_id)
        injuries.append({'citizen_id':c['citizen_id'],'hp_before':row['current_hp'],'hp_after':hp})
    connection.execute('UPDATE buildings SET current_hp=? WHERE building_id=?',(after,bid))
    connection.execute("INSERT INTO building_state_events(building_id,event_type,occurred_at,event_data) VALUES (?,'hostile_damage',?,?)",(bid,now,json.dumps({'attack_id':attack_id,'hp_before':before,'hp_after':after})))
    if after>0:
        for j in state['jobs']:
            if j['target_building_id']!=bid or j['status'] not in ('active','paused'):continue
            data=json.loads(j['inputs_spent'])
            if j['job_type']=='repair':
                data['_start_hp']=data['_start_hp']-(before-after)
                extra=(before-after)/state['config']['repairs']['hp_per_worker_hour']*3600
                connection.execute('UPDATE settlement_jobs SET work_required=work_required+? WHERE job_id=?',(extra,j['job_id']))
            elif j['job_type']=='construction':data['_damage']=data.get('_damage',0)+(before-after)
            else:continue
            connection.execute('UPDATE settlement_jobs SET inputs_spent=? WHERE job_id=?',(json.dumps(data),j['job_id']))
    report.append({'building_id':bid,'type':b['building_type'],'hp_before':before,'hp_after':after,'injuries':injuries,'destroyed':after==0})
    if vault_loss:report[-1]['vault_credits']=vault_loss
    if after==0:
        investment,work=invested(state,b);salvage={r:investment[r]*state['config']['structural']['salvage'][r] for r in MATERIALS}
        ammo=sum(i['quantity'] for i in state['inventory'] if i['building_id']==bid)
        release(connection,state['settlement']['settlement_id'],bid,now)
        connection.execute("UPDATE buildings SET status=?,destroyed_at=?,cleared_at=? WHERE building_id=?",('cleared' if tent else 'ruined',now,now if tent else None,bid))
        connection.execute('UPDATE military_inventory SET quantity=0,updated_at=? WHERE building_id=?',(now,bid))
        connection.execute("INSERT INTO building_state_events(building_id,event_type,occurred_at,event_data) VALUES (?,'hostile_destruction',?,?)",(bid,now,json.dumps({'attack_id':attack_id,'salvage':{} if tent else salvage,'work_required':work})))
        if ammo and bid not in exploded:
            exploded.add(bid)
            # Each store detonates once. Work from fresh state so ruined buildings cannot explode again.
            for other in state['buildings']:
                if other['building_id']==bid:continue
                falloff=settings()['Combat Raids']['secondary_explosion_falloff']/100
                loss=state['config']['structural']['explosion_hp_per_round']*ammo*falloff**math.ceil(distance(state,b,other))
                if loss<.01:continue
                hit(connection,read_state(connection),other['building_id'],loss,now,attack_id,report,exploded)
    replace_admin(connection,read_state(connection),now)
    rebalance(connection,read_state(connection),now)


def speed(state,job):
    if job['status'] not in ('active','paused'):return 0
    b=next(b for b in state['buildings'] if b['building_id']==job['target_building_id'])
    if b['status']!='ruined':return 0
    crew=[c for c in state['citizens'] if c['job_id']==job['job_id']]
    from game.consequences import deliberate
    if coverage(state,b)<state['config']['construction']['coverage_fraction'] and not all(deliberate(state,c) for c in crew):return 0
    if not crew:return 0
    from game.support import best
    return state['config']['scavenging']['crew_speed'][len(crew)-1]*sum(productivity(state,c) for c in crew)/len(crew)*(1+best(state,'scavenge_bonus')/100)


def progress(connection,state,job,seconds,now):
    rate=speed(state,job);done=min(job['work_required'],job['work_completed']+rate*seconds)
    complete=done>=job['work_required']-1e-7
    from game.support import best
    amounts={r:v*(done-job['work_completed'])/job['work_required']*(1+best(state,'salvage_bonus')/100) for r,v in json.loads(job['inputs_spent'])['salvage'].items()}
    credit(connection,read_state(connection),amounts,now)
    connection.execute('UPDATE settlement_jobs SET work_completed=?,status=?,last_processed_at=?,completed_at=?,pause_reason=? WHERE job_id=?',(done,'completed' if complete else 'active' if rate else 'paused',now,now if complete else None,None if rate else 'Assign safe scavengers',job['job_id']))
    if complete:
        connection.execute("UPDATE buildings SET status='cleared',cleared_at=? WHERE building_id=?",(now,job['target_building_id']))
        connection.execute('UPDATE citizens SET unemployed_since=? WHERE citizen_id IN (SELECT citizen_id FROM citizen_assignments WHERE job_id=? AND ended_at IS NULL)',(now,job['job_id']))
        connection.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='ruin_cleared' WHERE job_id=? AND ended_at IS NULL",(now,job['job_id']))


def command(connection,state,bid,cid,now,exposed=False):
    if 'structural' not in state['config']:raise ValueError('Enable structural combat first.')
    b=next((b for b in state['buildings'] if b['building_id']==bid),None)
    c=next((c for c in state['citizens'] if c['citizen_id']==cid),None)
    if not b or b['status']!='ruined':raise ValueError('Choose your own ruined building.')
    if c and c['building_id']==bid and c['assignment']=='scavenging':return
    if not c or c.get('away') or c['assignment']!='unassigned':raise ValueError('Choose an unassigned citizen at home.')
    unsafe=coverage(state,b)<state['config']['construction']['coverage_fraction']
    if unsafe and (not exposed or 'consequences' not in state['config']):raise ValueError('Outside Oxygen coverage: confirm dangerous exposure before assigning.')
    job=next((j for j in state['jobs'] if j['job_type']=='building_salvage' and j['target_building_id']==bid and j['status'] in ('active','paused')),None)
    if job:jid=job['job_id']
    else:
        if now>=state['season']['finalization_at']:raise ValueError('New scavenging projects are closed during the final three hours.')
        row=connection.execute("SELECT event_data FROM building_state_events WHERE building_id=? AND event_type='hostile_destruction' ORDER BY state_event_id DESC LIMIT 1",(bid,)).fetchone()
        data=json.loads(row[0])
        jid=connection.execute("INSERT INTO settlement_jobs(settlement_id,job_type,target_type,target_building_id,work_required,status,created_at,last_processed_at,inputs_spent) VALUES (?,'building_salvage','building',?,?,'paused',?,?,?)",(state['settlement']['settlement_id'],bid,data['work_required'],now,now,json.dumps({'salvage':data['salvage']}))).lastrowid
    if sum(c['job_id']==jid for c in state['citizens'])>=len(state['config']['scavenging']['crew_speed']):raise ValueError('All scavenging slots are filled.')
    aid=connection.execute("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,building_id,job_id,assigned_at) VALUES (?,?,'scavenging',?,?,?)",(cid,state['settlement']['settlement_id'],bid,jid,now)).lastrowid
    connection.execute('UPDATE citizens SET unemployed_since=NULL WHERE citizen_id=?',(cid,))
    if unsafe:
        from game.consequences import authorize
        authorize(connection,state,aid,now)


def panel(state,token):
    if 'structural' not in state['config']:return ''
    from game.building_views import form
    free=[c for c in state['citizens'] if c['assignment']=='unassigned' and not c.get('away')]
    result='<section class="production-panel"><h2>Destroyed buildings</h2><p>Salvage ruins gradually, then rebuild on their cleared tiles. Tents leave no ruin.</p>'
    for b in state['buildings']:
        if b['status']!='ruined':continue
        bid=b['building_id'];result+=f'<div id="ruin-{bid}"><h3>{escape(state["config"]["buildings"][b["building_type"]]["name"])} #{bid}</h3>'
        choices=''.join(f'<option value="{c["citizen_id"]}">{escape(c["name"])}</option>' for c in free)
        warning='<label><input type="checkbox" name="exposed" value="1" required>Danger: outside Oxygen. Rapid HP loss; emergency evacuation at 25% HP.</label>' if coverage(state,b)<state['config']['construction']['coverage_fraction'] else ''
        if free:result+=form(token,'salvage_ruin',f'<label>Scavenger <select name="citizen_id">{choices}</select></label>{warning}<button>Salvage and clear</button>',building_id=bid)
        for c in state['citizens']:
            if c['building_id']==bid and c['assignment']=='scavenging':result+=form(token,'release',f'<button>Release {escape(c["name"])}</button>',building_id=bid,citizen_id=c['citizen_id'])
        job=next((j for j in state['jobs'] if j['target_building_id']==bid and j['job_type']=='building_salvage'),None)
        if job:result+=f'<p>{100*job["work_completed"]/job["work_required"]:.1f}% cleared.</p>'
        result+='</div>'
    return result+'</section>'

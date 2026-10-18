"""Private persisted loot, gradual delivery, and manual scavenging assignments."""

from contextlib import closing
import json
import random
import secrets
import sqlite3
import time

from database.create_database import connect_database
from game.settlement import load_config, read_state
from game.buildings import footprint, productivity


def enable(connection,state,now):
    if state['season']['config_version'] in ('prototype_v4','prototype_v5','prototype_v6','prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):return
    config=load_config('prototype_v4'); sid=state['settlement']['settlement_id']; season=state['season']['season_id']
    connection.execute("UPDATE seasons SET config_version='prototype_v4' WHERE season_id=?",(season,))
    rng=random.Random(state['season']['map_seed'])
    occupied=[(b['origin_x'],b['origin_y'],*footprint(state,b)) for b in state['buildings'] if b['status'] not in ('cleared','demolished')]
    preferred=[(14,18),(23,21),(18,14),(21,22)]
    types=list(config['derelicts'])
    for index in range(config['scavenging']['map_count']):
        kind=types[index%len(types)];info=config['derelicts'][kind];w,h=info['footprint']
        for attempt in range(5000):
            x,y=preferred[index] if index<len(preferred) and attempt==0 else (rng.randrange(40-w+1),rng.randrange(40-h+1))
            if not any(x<ox+ow and x+w>ox and y<oy+oh and y+h>oy for ox,oy,ow,oh in occupied):break
        else:break
        occupied.append((x,y,w,h))
        existing=connection.execute('SELECT season_derelict_id FROM season_derelicts WHERE season_id=? AND derelict_type=? AND origin_x=? AND origin_y=?',(season,kind,x,y)).fetchone()
        common=existing[0] if existing else connection.execute('''INSERT INTO season_derelicts(season_id,derelict_type,origin_x,origin_y)
            VALUES (?,?,?,?)''',(season,kind,x,y)).lastrowid
        nonce=secrets.token_hex(32);private=random.Random(nonce)
        loot={r:private.randint(*limits) for r,limits in info['loot'].items()}
        connection.execute('''INSERT INTO settlement_derelicts
            (settlement_id,season_id,season_derelict_id,status,random_key_ref,random_nonce,random_result,created_at)
            VALUES (?,?,?,'untouched','prototype-private-v1',?,?,?)''',(sid,season,common,nonce,json.dumps(loot),now))
    from game.simulation import _event
    _event(connection,state,'prototype_config_enabled',now,{'from':state['season']['config_version'],'to':'prototype_v4'})


def safe_coverage(state,derelict,utility=None):
    from game.economy import utilities, coverage_fraction
    w,h=state['config']['derelicts'][derelict['derelict_type']]['footprint']
    utility=utility if utility is not None else utilities(state)
    return coverage_fraction(state,derelict['origin_x'],derelict['origin_y'],w,h,utility['zones']['oxygen'])


def speed(state,job,utility=None):
    d=next(d for d in state['derelicts'] if d['settlement_derelict_id']==job['target_derelict_id'])
    from game.consequences import deliberate
    if d['status']=='cleared' or (safe_coverage(state,d,utility)<state['config']['construction']['coverage_fraction'] and not all(deliberate(state,c) for c in state['citizens'] if c['job_id']==job['job_id'])):return 0
    workers=[c for c in state['citizens'] if c['job_id']==job['job_id'] and c['assignment']=='scavenging']
    if not workers:return 0
    from game.support import best
    return state['config']['scavenging']['crew_speed'][len(workers)-1]*sum(productivity(state,c) for c in workers)/len(workers)*(1+best(state,'scavenge_bonus',utility)/100)


def progress(connection,state,job,seconds,now):
    rate=speed(state,job);done=min(job['work_required'],job['work_completed']+rate*seconds)
    if job['work_required']-done<1e-7:done=job['work_required']
    complete=done==job['work_required']
    d=next(d for d in state['derelicts'] if d['settlement_derelict_id']==job['target_derelict_id'])
    totals=json.loads(d['random_result']);recovered=json.loads(d['recovered_loot'])
    earned_delta={}
    from game.support import best
    salvage_bonus=best(state,'salvage_bonus')/100
    for r in ('food','water','scrap','metal','electronics'):
        bonus=salvage_bonus if r in ('scrap','metal','electronics') else 0
        delta=totals[r]*max(0,done-job['work_completed'])/job['work_required']*(1+bonus)
        recovered[r]=recovered.get(r,0)+delta;earned_delta[r]=delta
    # Quantities were settled by economy.advance_resources with the same elapsed
    # interval. Here we retain delivery progress, so reloads cannot duplicate loot.
    connection.execute('''UPDATE settlement_derelicts SET recovered_loot=?,status=?,cleared_at=? WHERE settlement_derelict_id=?''',
                       (json.dumps(recovered),'cleared' if complete else 'scavenging',now if complete else None,d['settlement_derelict_id']))
    connection.execute('''UPDATE settlement_jobs SET work_completed=?,last_processed_at=?,status=?,completed_at=?,
        started_at=COALESCE(started_at,?),pause_reason=? WHERE job_id=?''',(done,now,'completed' if complete else 'active' if rate else 'paused',
        now if complete else None,state['settlement']['simulation_processed_at'] if rate else None,None if rate else 'No safe effective scavengers',job['job_id']))
    if complete:
        connection.execute('''UPDATE citizens SET unemployed_since=? WHERE citizen_id IN
            (SELECT citizen_id FROM citizen_assignments WHERE job_id=? AND ended_at IS NULL)''',(now,job['job_id']))
        connection.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='completed' WHERE job_id=? AND ended_at IS NULL",(now,job['job_id']))
    if any(earned_delta.values()):
        from game.simulation import _event
        _event(connection,state,'prototype_scavenged',now,{'derelict_id':d['settlement_derelict_id'],'earned':earned_delta,'delivery':'limited by storage'})
    from game.population import discover
    discover(connection,state,d,done/job['work_required'],now)


def assign(path,action,derelict_id,citizen_id,now=None,exposed=False):
    from game.simulation import _advance, _event
    now=int(time.time()) if now is None else now
    with closing(connect_database(path)) as c,c:
        c.row_factory=sqlite3.Row;c.execute('BEGIN IMMEDIATE');state=read_state(c)
        from game.admin_controls import require_running
        require_running(c, state)
        if not state or state['season']['config_version'] not in ('prototype_v4','prototype_v5','prototype_v6','prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):raise ValueError('Enable civilian production first.')
        if state['settlement']['status']!='active' or state['season']['status']=='finished':raise ValueError('This settlement is not active.')
        if now<state['settlement']['simulation_processed_at']:raise ValueError('The clock is earlier than the save.')
        if action not in ('assign','release'):raise ValueError('Unknown scavenging action.')
        _advance(c,state,now);state=read_state(c)
        if state['season']['status']=='finished':return state
        if state['settlement']['status']!='active':return state
        at=state['season']['paused_at'] if state['season']['status']=='paused' else now
        citizen=next((a for a in state['citizens'] if a['citizen_id']==citizen_id),None)
        d=next((d for d in state['derelicts'] if d['settlement_derelict_id']==derelict_id),None)
        if not citizen or citizen['current_hp']<=0 or not d or d['status']=='cleared':raise ValueError('Choose a living citizen and an uncleared derelict.')
        if c.execute('SELECT 1 FROM attack_citizens WHERE citizen_id=? AND released_at IS NULL',(citizen_id,)).fetchone():raise ValueError('That citizen is away.')
        job=next((j for j in state['jobs'] if j['target_derelict_id']==derelict_id and j['status'] in ('active','paused')),None)
        if action=='release':
            if not job or citizen['job_id']!=job['job_id'] or citizen['assignment']!='scavenging':raise ValueError('This citizen is not working here.')
            c.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='released' WHERE assignment_id=?",(at,citizen['assignment_id']))
            c.execute('UPDATE citizens SET unemployed_since=? WHERE citizen_id=?',(at,citizen_id))
        else:
            if job and citizen['job_id']==job['job_id']:return state
            if citizen['assignment']!='unassigned':raise ValueError('Release this citizen from their current job first.')
            if safe_coverage(state,d)<state['config']['construction']['coverage_fraction'] and (not exposed or 'consequences' not in state['config']):raise ValueError('Confirm dangerous Oxygen exposure before sending scavengers.')
            if at>=state['season']['finalization_at'] and not job:raise ValueError('New scavenging projects are closed during the final three hours.')
            if not job:
                info=state['config']['derelicts'][d['derelict_type']]
                jid=c.execute('''INSERT INTO settlement_jobs(settlement_id,job_type,target_type,target_derelict_id,
                    work_required,status,created_at,last_processed_at) VALUES (?,'scavenging','derelict',? ,?,'paused',?,?)''',
                    (state['settlement']['settlement_id'],derelict_id,info['minutes']*60,at,at)).lastrowid
                c.execute("UPDATE settlement_derelicts SET status='scavenging' WHERE settlement_derelict_id=?",(derelict_id,))
            else:jid=job['job_id']
            limit=state['config']['derelicts'][d['derelict_type']]['workers']
            if sum(a['job_id']==jid for a in state['citizens'])>=limit:raise ValueError('All scavenger slots are filled.')
            aid=c.execute('''INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,job_id,assigned_at)
                VALUES (?,?,'scavenging',?,?)''',(citizen_id,state['settlement']['settlement_id'],jid,at)).lastrowid
            if exposed and 'consequences' in state['config'] and safe_coverage(state,d)<state['config']['construction']['coverage_fraction']:
                from game.consequences import authorize
                authorize(c,state,aid,at)
            c.execute('UPDATE citizens SET unemployed_since=NULL WHERE citizen_id=?',(citizen_id,))
        _event(c,state,'prototype_scavenging_assignment',at,{'action':action,'citizen_id':citizen_id,'derelict_id':derelict_id})
        return read_state(c)

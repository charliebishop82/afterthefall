"""Staffed military batches on existing jobs, units and inventory tables."""
from contextlib import closing
from html import escape
import json
import math
import sqlite3

from database.create_database import connect_database
from game.settlement import read_state
from game.buildings import spec, productivity


def enabled(state):
    return state['season']['config_version'] in ('prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13')


def enable(connection, state, now):
    if enabled(state):
        return
    from game.repairs import enable as enable_repairs
    enable_repairs(connection, state, now)
    state = read_state(connection)
    connection.execute("UPDATE seasons SET config_version='prototype_v9' WHERE season_id=?", (state['season']['season_id'],))
    from game.simulation import _event
    _event(connection, state, 'prototype_config_enabled', now, {'from':state['season']['config_version'], 'to':'prototype_v9'})


def capacity(state, building):
    if building['status'] not in ('active','upgrading') or building['current_hp'] <= 0:
        return 0
    definition = spec(state, building)
    return math.floor(max(definition.get(k, 0) for k in ('drone_capacity','repair_drone_capacity','munition_capacity')) * min(1, building['current_hp']/definition['hp']) + 1e-9)


def occupancy(state, bid, exclude_job=None):
    stored = sum(u['home_building_id']==bid and u['status']!='destroyed' for u in state.get('units', []))
    stored += sum(i['quantity'] for i in state.get('munition_reservations',[]) if i['building_id']==bid)
    stored += sum(i['quantity'] for i in state.get('inventory', []) if i['building_id']==bid)
    for job in state['jobs']:
        if job['job_type']=='manufacturing' and job['status'] in ('active','paused') and job['job_id']!=exclude_job:
            inputs=json.loads(job['inputs_spent'])
            stored += bool(inputs.get('paid') and inputs.get('home_id')==bid)
    return stored


def home_for(state, unit_type, exclude_job=None):
    from game.economy import utilities
    status=utilities(state)['buildings']
    for b in state['buildings']:
        if b['building_type']==state['config']['units'][unit_type]['storage'] and b['status']=='active' and not status[b['building_id']]['reason'] and occupancy(state,b['building_id'],exclude_job)<capacity(state,b):
            return b
    return None


def reason(state, job):
    from game.economy import utilities
    factory=next(b for b in state['buildings'] if b['building_id']==job['production_building_id'])
    status=utilities(state)['buildings'][factory['building_id']]
    if status['reason']:
        return status['reason']
    data=json.loads(job['inputs_spent'])
    if data.get('paid'):
        home=next((b for b in state['buildings'] if b['building_id']==data['home_id']),None)
        if not home or home['status']!='active' or utilities(state)['buildings'][home['building_id']]['reason'] or occupancy(state,home['building_id'],job['job_id'])>=capacity(state,home):
            return 'Waiting for compatible storage'
    elif home_for(state,job['output_type'],job['job_id']) is None:
        return 'Waiting for compatible storage'
    if not data.get('paid'):
        return 'Waiting for materials'
    return ''


def speed(state, job):
    if job['status'] not in ('active','paused') or reason(state,job):
        return 0
    b=next(b for b in state['buildings'] if b['building_id']==job['production_building_id'])
    definition=spec(state,b)
    workers=[c for c in state['citizens'] if c['assignment']=='production' and c['building_id']==b['building_id']]
    return sum(productivity(state,c) for c in workers)*min(1,b['current_hp']/definition['hp'])*(1+definition['production_bonus']/100)


def prepare(connection, state, now):
    """Start one unit at a time; reserve its destination before spending inputs."""
    if not enabled(state) or now>=state['season']['ends_at'] or state['settlement']['status']!='active' or state['season']['status'] not in ('active','finalizing'):
        return False
    from game.trading import available
    changed=False
    factories=[b for b in state['buildings'] if b['building_type'] in ('drone_factory','munitions_factory')]
    for factory in factories:
        current=read_state(connection)
        jobs=[j for j in current['jobs'] if j['job_type']=='manufacturing' and j['production_building_id']==factory['building_id'] and j['status'] in ('queued','active','paused')]
        job=next((j for j in jobs if j['status'] in ('active','paused')),None)
        if not job and jobs:
            job=min(jobs,key=lambda j:(j['queue_position'],j['job_id']))
            connection.execute("UPDATE settlement_jobs SET status='paused' WHERE job_id=?",(job['job_id'],));changed=True
        if not job:
            continue
        data=json.loads(job['inputs_spent']);unit=current['config']['units'][job['output_type']]
        if not data.get('paid'):
            from game.economy import utilities
            ready=not utilities(current)['buildings'][factory['building_id']]['reason']
            home=home_for(current,job['output_type'],job['job_id'])
            if ready and home and all(available(current,r)+1e-9>=unit[r] for r in ('metal','electronics')):
                connection.execute('UPDATE settlement_resources SET metal=metal-?,electronics=electronics-?,updated_at=? WHERE settlement_id=?',(unit['metal'],unit['electronics'],now,current['settlement']['settlement_id']))
                data.update(paid=True,home_id=home['building_id'])
                connection.execute('UPDATE settlement_jobs SET inputs_spent=?,started_at=COALESCE(started_at,?) WHERE job_id=?',(json.dumps(data),now,job['job_id']));changed=True
        current=read_state(connection);job=next(j for j in current['jobs'] if j['job_id']==job['job_id'])
        why=reason(current,job)
        status='paused' if why else 'active'
        if status!=job['status'] or why!=job['pause_reason']:
            connection.execute('UPDATE settlement_jobs SET status=?,pause_reason=? WHERE job_id=?',(status,why or None,job['job_id']));changed=True
    return changed


def next_boundary(state):
    if not enabled(state):
        return None
    from game.economy import rates, utilities
    from game.trading import available
    flow=rates(state);operating=utilities(state)['buildings'];boundaries=[]
    for job in state['jobs']:
        if job['job_type']!='manufacturing' or job['status'] not in ('active','paused') or json.loads(job['inputs_spent']).get('paid'):
            continue
        if operating[job['production_building_id']]['reason'] or home_for(state,job['output_type'],job['job_id']) is None:
            continue
        unit=state['config']['units'][job['output_type']];waits=[]
        for r in ('metal','electronics'):
            missing=unit[r]-available(state,r)
            if missing>1e-8:
                if flow[r]['net']<=0:
                    break
                waits.append(math.ceil(missing/flow[r]['net']*3600))
        else:
            if waits:boundaries.append(state['settlement']['simulation_processed_at']+max(1,max(waits)))
    return min(boundaries) if boundaries else None


def progress(connection, state, job, seconds, now):
    done=min(job['work_required'],job['work_completed']+seconds*speed(state,job))
    if job['work_required']-done<1e-7:
        done=job['work_required']
    connection.execute('UPDATE settlement_jobs SET work_completed=?,last_processed_at=? WHERE job_id=?',(done,now,job['job_id']))
    if done<job['work_required']:
        return
    data=json.loads(job['inputs_spent']);unit=state['config']['units'][job['output_type']]
    sid=state['settlement']['settlement_id'];bid=data['home_id']
    if unit['category']=='Drone':
        connection.execute("INSERT INTO military_units(settlement_id,unit_type,current_hp,home_building_id,status,created_at) VALUES (?,?,?,?,'available',?)",(sid,job['output_type'],unit['hp'],bid,now))
    else:
        connection.execute('''INSERT INTO military_inventory(settlement_id,building_id,unit_type,quantity,updated_at) VALUES (?,?,?,1,?)
            ON CONFLICT(building_id,unit_type) DO UPDATE SET quantity=quantity+1,updated_at=excluded.updated_at''',(sid,bid,job['output_type'],now))
    data['remaining']-=1;data['produced']+=1
    if not data['remaining'] and job['repeat_production'] and now<state['season']['finalization_at']:
        data['remaining']=job['output_quantity']
    continuing=data['remaining']>0
    data['paid']=False;data.pop('home_id',None)
    connection.execute('UPDATE settlement_jobs SET work_completed=?,status=?,completed_at=?,inputs_spent=?,pause_reason=? WHERE job_id=?',(0 if continuing else done,'paused' if continuing else 'completed',None if continuing else now,json.dumps(data),'Waiting for next unit' if continuing else None,job['job_id']))
    from game.simulation import _event
    _event(connection,state,'military_unit_produced',now,{'job_id':job['job_id'],'unit_type':job['output_type'],'home_building_id':bid})


def command(path, action, now, *, building_id=None, unit_type=None, quantity=1, repeat=False, job_id=None):
    from game.simulation import _advance
    with closing(connect_database(path)) as c,c:
        c.row_factory=sqlite3.Row;c.execute('BEGIN IMMEDIATE');state=read_state(c)
        from game.admin_controls import require_running
        require_running(c, state)
        if not state or state['settlement']['status']!='active' or state['season']['status']=='finished':
            raise ValueError('This settlement is not active.')
        if now<state['settlement']['simulation_processed_at']:
            raise ValueError('The clock is earlier than the saved state.')
        _advance(c,state,now);state=read_state(c)
        if state['settlement']['status']!='active' or state['season']['status']=='finished':
            return state
        at=state['season']['paused_at'] if state['season']['status']=='paused' else now
        if action=='enable':
            enable(c,state,at);return read_state(c)
        if not enabled(state):
            raise ValueError('Enable military production first.')
        if action=='queue':
            if at>=state['season']['finalization_at'] or state['season']['status']=='finalizing':
                raise ValueError('New manufacturing batches are closed during the final three hours.')
            unit=state['config']['units'].get(unit_type)
            factory=next((b for b in state['buildings'] if b['building_id']==building_id),None)
            if not unit or not factory or factory['status']!='active' or factory['building_type']!=unit['factory']:
                raise ValueError('Choose your own completed compatible factory and unit type.')
            if type(quantity) is not int or not 1<=quantity<=100 or type(repeat) is not bool:
                raise ValueError('Use a whole batch of 1–100 units.')
            position=max([j['queue_position'] for j in state['jobs'] if j['production_building_id']==building_id]+[0])+1
            data={'paid':False,'remaining':quantity,'produced':0}
            c.execute("INSERT INTO settlement_jobs(settlement_id,job_type,target_type,target_building_id,production_building_id,output_type,output_quantity,queue_position,repeat_production,work_required,status,created_at,last_processed_at,inputs_spent) VALUES (?,'manufacturing','building',?,?,?,?,?,?,?,'queued',?,?,?)",(state['settlement']['settlement_id'],building_id,building_id,unit_type,quantity,position,int(repeat),unit['seconds'],at,at,json.dumps(data)))
            prepare(c,read_state(c),at)
        elif action in ('stop','cancel'):
            job=next((j for j in state['jobs'] if j['job_id']==job_id and j['job_type']=='manufacturing' and j['status'] in ('queued','active','paused')),None)
            if not job:
                raise ValueError('Choose your own unfinished manufacturing batch.')
            if action=='stop':
                c.execute('UPDATE settlement_jobs SET repeat_production=0 WHERE job_id=?',(job_id,))
            else:
                if json.loads(job['inputs_spent']).get('paid'):
                    raise ValueError('The current unit is funded. Let it finish; continuous production can be stopped.')
                c.execute("UPDATE settlement_jobs SET status='cancelled',pause_reason='Cancelled by player' WHERE job_id=?",(job_id,))
        else:
            raise ValueError('Unknown manufacturing action.')
        return read_state(c)


def panel(state, token):
    hidden=f'<input type="hidden" name="token" value="{escape(token,quote=True)}">'
    def form(action,body,**fields):
        return '<form method="post" action="/manufacturing">'+hidden+f'<input type="hidden" name="action" value="{action}">'+''.join(f'<input type="hidden" name="{k}" value="{escape(str(v),quote=True)}">' for k,v in fields.items())+body+'</form>'
    html='<section class="production-panel" id="military"><h2>Military production</h2>'
    if not enabled(state):
        return html+form('enable','<p>Add drone and munitions factories, upgrades and compatible storage.</p><button>Enable military production</button>')+'</section>'
    html+='<p>Manufacture and store equipment. Enable support and defense for offensive drone resource raids and automatic air/ground drone defense. Enable maintenance and building management for drone servicing and Repair Drone orders. Missiles and interceptors await later increments.</p><p>Inputs are paid for each unit when work can start. Factories pause for workers, utilities, materials or compatible storage.</p>'
    factories=[b for b in state['buildings'] if b['building_type'] in ('drone_factory','munitions_factory') and b['status']=='active']
    if not factories:
        html+='<p>No completed military factory yet. Build and staff a Drone Factory or Munitions Factory, provide utilities and compatible storage, then queue equipment here.</p><a href="#construction">Build military infrastructure</a>'
    html+='<p><a href="#conflict">Go to combat: declare war and launch raids</a></p>'
    for b in state['buildings']:
        if b['building_type'] in ('drone_factory','munitions_factory') and b['status']=='active':
            options=''.join(f'<option value="{key}">{escape(u["name"])} — {u["metal"]:g} Metal, {u["electronics"]:g} Electronics, {u["seconds"]/60:g} base minutes</option>' for key,u in state['config']['units'].items() if u['factory']==b['building_type'])
            html+=form('queue',f'<label>Produce at {escape(state["config"]["buildings"][b["building_type"]]["name"])} #{b["building_id"]}<select name="unit_type">{options}</select></label><label>Batch quantity <input name="quantity" type="number" min="1" max="100" value="1" required></label><label><input type="checkbox" name="repeat" value="1">Repeat batch until stopped</label><button>Queue batch</button>',building_id=b['building_id'])
        if capacity(state,b):
            html+=f'<p>{escape(state["config"]["buildings"][b["building_type"]]["name"])} #{b["building_id"]}: {occupancy(state,b["building_id"])} / {capacity(state,b)} slots (includes funded units).</p>'
    for key,u in state['config']['units'].items():
        count=sum(x['unit_type']==key and x['status']!='destroyed' for x in state['units'])+sum(x['quantity'] for x in state['inventory'] if x['unit_type']==key)
        html+=f'<p>{escape(u["name"])}: {count} stored.</p>'
    for j in state['jobs']:
        if j['job_type']!='manufacturing' or j['status'] not in ('queued','active','paused'):
            continue
        data=json.loads(j['inputs_spent'])
        html+=f'<p>Batch #{j["job_id"]} · {escape(state["config"]["units"][j["output_type"]]["name"])} · {data["remaining"]} remaining · {data["produced"]} produced · <span id="job-{j["job_id"]}">{100*j["work_completed"]/j["work_required"]:.1f}% of current unit · {escape(j["pause_reason"] or j["status"])}</span>.</p><progress id="progress-{j["job_id"]}" max="100" value="{100*j["work_completed"]/j["work_required"]}">Current unit</progress>'
        if j['repeat_production']:
            html+=form('stop','<button>Stop repeating</button>',job_id=j['job_id'])
        if not data.get('paid'):
            html+=form('cancel','<button class="secondary">Cancel unfunded remainder</button>',job_id=j['job_id'])
    return html+'</section>'

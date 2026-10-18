"""Paid drone servicing and manually or automatically targeted Repair Drones."""
import json
from html import escape
from game.settlement import read_state
from game.buildings import spec


def enabled(state):return 'maintenance' in state['config']


def enable(connection,state,now):
    if enabled(state):return
    from game.support import enable as support
    support(connection,state,now)
    connection.execute("UPDATE seasons SET config_version='prototype_v11' WHERE season_id=?",(state['season']['season_id'],))
    from game.simulation import _event
    _event(connection,state,'prototype_config_enabled',now,{'from':state['season']['config_version'],'to':'prototype_v11'})


def workshop(state,bid=None):
    from game.economy import utilities
    status=utilities(state)['buildings']
    return next((b for b in state['buildings'] if b['building_type'] in ('engineering_workshop','starter_engineering_workshop') and (bid is None or b['building_id']==bid) and b['status']=='active' and not status[b['building_id']]['reason']),None)


def orders(state):return state.get('repair_drone_orders',{})


def order(connection,state,uid,mode,target,now):
    from game.simulation import _event
    _event(connection,state,'prototype_repair_drone_order',now,{'unit_id':uid,'mode':mode,'target':target})


def eligible(state,b):
    return b['status']=='active' and 0<b['current_hp']<spec(state,b)['hp'] and b['building_type'] not in ('pup_tent','upgraded_tent')


def repair_cost(state,u):
    unit=state['config']['units'][u['unit_type']]
    fraction=state['config']['maintenance']['drone_material_fraction']*max(0,1-u['current_hp']/unit['hp'])
    return {r:unit.get(r,0)*fraction for r in ('scrap','metal','electronics')}


def command(connection,state,action,uid,bid,now):
    if action=='enable_maintenance':enable(connection,state,now);return
    if not enabled(state):raise ValueError('Enable maintenance and building management first.')
    u=next((u for u in state['units'] if u['unit_id']==uid),None)
    if not u or u['status'] not in ('available','repairing') or u['current_hp']<=0:raise ValueError('Choose your own surviving drone at home.')
    job=next((j for j in state['jobs'] if j['job_type']=='drone_repair' and j['target_unit_id']==uid and j['status'] in ('active','paused')),None)
    if action=='service_drone':
        if job:return
        if u['status']!='available':raise ValueError('This drone is busy.')
        if now>=state['season']['finalization_at'] or state['season']['status']=='finalizing':raise ValueError('New drone repairs are closed during the final three hours.')
        shop=workshop(state,bid)
        if not shop:raise ValueError('A staffed, functioning Engineering Workshop is required.')
        if any(j['job_type']=='drone_repair' and j['production_building_id']==shop['building_id'] and j['status'] in ('active','paused') for j in state['jobs']):raise ValueError('This workshop is already servicing a drone.')
        missing=state['config']['units'][u['unit_type']]['hp']-u['current_hp']
        if missing<=0:raise ValueError('This drone is already at full health.')
        price=repair_cost(state,u)
        from game.trading import available
        if any(available(state,r)+1e-9<v for r,v in price.items()):raise ValueError('Not enough unreserved repair materials.')
        connection.execute('UPDATE settlement_resources SET scrap=scrap-?,metal=metal-?,electronics=electronics-?,updated_at=? WHERE settlement_id=?',(*price.values(),now,state['settlement']['settlement_id']))
        connection.execute("INSERT INTO settlement_jobs(settlement_id,job_type,target_type,target_unit_id,production_building_id,work_required,status,created_at,last_processed_at,inputs_spent) VALUES (?,'drone_repair','unit',?,?,?,'active',?,?,?)",(state['settlement']['settlement_id'],uid,shop['building_id'],missing/state['config']['maintenance']['drone_hp_per_hour']*3600,now,now,json.dumps({**price,'_start_hp':u['current_hp']})))
        connection.execute("UPDATE military_units SET status='repairing' WHERE unit_id=?",(uid,))
        if u['unit_type']=='repair_drone':order(connection,state,uid,'off',None,now)
    else:
        if u['unit_type']!='repair_drone' or u['status']!='available':raise ValueError('Choose an available Repair Drone.')
        if action=='repair_drone_off':order(connection,state,uid,'off',None,now)
        elif action=='repair_drone_auto':
            if orders(state).get(str(uid),{}).get('mode')=='auto':return
            order(connection,state,uid,'auto',None,now)
        elif action=='repair_drone_target':
            if not workshop(state,u['home_building_id']):raise ValueError('The Repair Drone needs a functioning home workshop.')
            b=next((b for b in state['buildings'] if b['building_id']==bid),None)
            if not b or not eligible(state,b):raise ValueError('Choose your own damaged, surviving permanent building.')
            ensure_project(connection,state,b,now)
            order(connection,state,uid,'manual',bid,now)
        else:raise ValueError('Unknown maintenance action.')


def ensure_project(connection,state,b,now):
    if not any(j['job_type']=='repair' and j['target_building_id']==b['building_id'] and j['status'] in ('active','paused') for j in state['jobs']):
        from game.repairs import command as repairs
        # Automatic selection may catch an unaffordable candidate and try another.
        # Roll back that attempt, including any pending Town Hall regeneration.
        connection.execute('SAVEPOINT maintenance_project')
        try:
            repairs(connection,state,'repair',b['building_id'],None,now)
        except Exception:
            connection.execute('ROLLBACK TO maintenance_project')
            connection.execute('RELEASE maintenance_project')
            raise
        connection.execute('RELEASE maintenance_project')
        return True
    return False


def prepare(connection,state,now):
    if not enabled(state):return False
    changed=False
    for u in state['units']:
        setting=orders(state).get(str(u['unit_id']),{})
        if u['unit_type']!='repair_drone' or u['status']!='available' or setting.get('mode') not in ('auto','manual') or not workshop(state,u['home_building_id']):continue
        current=read_state(connection)
        if setting['mode']=='manual':
            b=next((b for b in current['buildings'] if b['building_id']==setting['target']),None)
            active=any(j['job_type']=='repair' and j['target_building_id']==setting['target'] and j['status'] in ('active','paused') for j in current['jobs'])
            if not b or not eligible(current,b) or not active:
                order(connection,current,u['unit_id'],'off',None,now);changed=True;continue
        else:
            candidates=sorted((b for b in current['buildings'] if eligible(current,b)),key=lambda b:(b['current_hp']/spec(current,b)['hp'],b['building_id']))
            previous=next((b for b in candidates if b['building_id']==setting.get('target') and any(j['job_type']=='repair' and j['target_building_id']==b['building_id'] and j['status'] in ('active','paused') for j in current['jobs'])),None)
            if previous:candidates=[previous]
            b=None
            for candidate in candidates:
                try:created=ensure_project(connection,current,candidate,now)
                except ValueError:continue
                changed=changed or created
                b=candidate;break
            if not b:
                if setting.get('target') is not None:
                    order(connection,current,u['unit_id'],'auto',None,now);changed=True
                continue
            if setting.get('target')!=b['building_id']:
                order(connection,current,u['unit_id'],'auto',b['building_id'],now);changed=True
        try:created=ensure_project(connection,read_state(connection),b,now)
        except ValueError:continue
        changed=changed or created
    return changed


def building_speed(state,job):
    if not enabled(state):return 0
    b=next((b for b in state['buildings'] if b['building_id']==job['target_building_id']),None)
    if not b or not eligible(state,b):return 0
    total=0
    for u in state['units']:
        setting=orders(state).get(str(u['unit_id']),{})
        if u['unit_type']=='repair_drone' and u['status']=='available' and u['current_hp']>0 and setting.get('mode') in ('auto','manual') and setting.get('target')==b['building_id'] and workshop(state,u['home_building_id']):
            total+=state['config']['maintenance']['repair_drone_hp_per_hour']*min(1,u['current_hp']/state['config']['units']['repair_drone']['hp'])
    return total/state['config']['repairs']['hp_per_worker_hour']


def speed(state,job):
    u=next((u for u in state['units'] if u['unit_id']==job['target_unit_id']),None)
    return 1 if enabled(state) and job['status'] in ('active','paused') and u and u['status']=='repairing' and u['current_hp']>0 and workshop(state,job['production_building_id']) else 0


def progress(connection,state,job,seconds,now):
    rate=speed(state,job);done=min(job['work_required'],job['work_completed']+rate*seconds)
    if job['work_required']-done<1e-7:done=job['work_required']
    complete=done==job['work_required']
    connection.execute('UPDATE settlement_jobs SET work_completed=?,last_processed_at=?,status=?,completed_at=?,pause_reason=? WHERE job_id=?',(done,now,'completed' if complete else 'active' if rate else 'paused',now if complete else None,None if rate else 'Workshop unavailable',job['job_id']))
    u=next(u for u in state['units'] if u['unit_id']==job['target_unit_id'])
    hp=min(state['config']['units'][u['unit_type']]['hp'],json.loads(job['inputs_spent'])['_start_hp']+done*state['config']['maintenance']['drone_hp_per_hour']/3600)
    connection.execute('UPDATE military_units SET current_hp=?,status=? WHERE unit_id=?',(hp,'available' if complete else 'repairing',u['unit_id']))
    if complete:
        from game.simulation import _event
        _event(connection,state,'drone_repair_completed',now,{'unit_id':u['unit_id']})


def finish(connection,state,now):
    """Season cancellation releases service reservations without manufacturing refunds."""
    connection.execute("UPDATE military_units SET status='available' WHERE settlement_id=? AND status='repairing' AND current_hp>0",(state['settlement']['settlement_id'],))


def panel(state,token):
    from game.building_views import form,cost_label
    html='<section class="production-panel" id="maintenance"><h2>Drone maintenance</h2>'
    if not enabled(state):return html+form(token,'enable_maintenance','<p>Add drone repairs, Repair Drone orders, construction cancellation and demolition.</p><button>Enable maintenance and building management</button>')+'</section>'
    frozen=state['settlement']['status']!='active' or state['season']['status']=='finished'
    disabled=' disabled' if frozen else ''
    html+='<p>Each staffed, functioning workshop services one stored drone at a time, at 10 HP/hour. Repair Drones support paid building repairs at up to 10 HP/hour each. Turning orders off leaves any paid project paused for a crew or another drone.</p>'
    choices=''.join(f'<option value="{b["building_id"]}">{escape(state["config"]["buildings"][b["building_type"]]["name"])} #{b["building_id"]}</option>' for b in state['buildings'] if eligible(state,b))
    shops=''.join(f'<option value="{b["building_id"]}">Workshop #{b["building_id"]}</option>' for b in state['buildings'] if b['building_type'] in ('engineering_workshop','starter_engineering_workshop') and b['status']=='active')
    for u in state['units']:
        if u['status']=='destroyed':continue
        maximum=state['config']['units'][u['unit_type']]['hp']
        html+=f'<article class="food-card"><h3>{escape(state["config"]["units"][u["unit_type"]]["name"])} #{u["unit_id"]}</h3><p>{u["current_hp"]:.2f} / {maximum:g} HP · {escape(u["status"])}</p>'
        job=next((j for j in state['jobs'] if j['job_type']=='drone_repair' and j['target_unit_id']==u['unit_id'] and j['status'] in ('active','paused')),None)
        if job:
            html+=f'<p>Service progress: {100*job["work_completed"]/job["work_required"]:.1f}% · {escape(job["pause_reason"] or "Repairing at 10 HP/hour")}.</p>'
        if u['status']=='available' and u['current_hp']<maximum:
            html+=form(token,'service_drone',f'<p>Repair materials: {cost_label(repair_cost(state,u)) or "Free"}.</p><label>Service workshop<select name="building_id">{shops}</select></label><button{disabled if shops else " disabled"}>Repair drone #{u["unit_id"]}</button>',unit_id=u['unit_id'])
        if u['unit_type']=='repair_drone' and u['status']=='available':
            setting=orders(state).get(str(u['unit_id']),{'mode':'off','target':None})
            html+=f'<p>Order: {escape(setting["mode"])}'+(f' · building #{setting["target"]}' if setting.get('target') else '')+'</p>'
            html+=form(token,'repair_drone_auto',f'<button{disabled}>Automatic repairs #{u["unit_id"]}</button>',unit_id=u['unit_id'])
            html+=form(token,'repair_drone_off',f'<button class="secondary"{disabled}>Stop repair drone #{u["unit_id"]}</button>',unit_id=u['unit_id'])
            html+=form(token,'repair_drone_target',f'<label>Building to repair<select name="building_id">{choices}</select></label><button{disabled if choices else " disabled"}>Assign repair drone #{u["unit_id"]}</button>',unit_id=u['unit_id'])
        html+='</article>'
    return html+'</section>'

"""Rations and supply consequences on the simulated-minute grid."""
from contextlib import closing
from html import escape
import copy
import json
import sqlite3

from database.create_database import connect_database
from game.settlement import read_state


def enabled(state):
    return state.get('needs_clock') is not None


def morale_modifier(state):
    if not enabled(state):
        return 0
    return sum(state['config']['needs']['rations'][r][state['policies'][r+'_ration']]['morale'] for r in ('food','water'))


def shortages(state):
    from game.economy import rates
    from game.trading import available
    flow=rates(state)
    return {r:(available(state,r)<=1e-8 and flow[r]['consumption']>flow[r]['production']+1e-8) for r in ('food','water')}


def record(connection,state,now,clock):
    from game.simulation import _event
    _event(connection,state,'prototype_needs_clock',now,clock)


def synchronize(connection,state,now):
    if not enabled(state):
        return False
    clock=copy.deepcopy(state['needs_clock'])
    for resource,missing in shortages(state).items():
        if missing and clock['since'][resource] is None:
            clock['since'][resource]=now
        elif not missing:
            clock['since'][resource]=None
    if clock!=state['needs_clock']:
        record(connection,state,now,clock)
        return True
    return False


def next_boundary(state):
    if not enabled(state):
        return None
    if not any(shortages(state).values()) and not state['needs_clock']['pending']:
        return None
    start=state['settlement']['simulation_processed_at'];anchor=state['recovery_clock']['anchor']
    quantum=state['config']['recovery']['tick_seconds']
    result=anchor+((start-anchor)//quantum+1)*quantum
    for resource,since in state['needs_clock']['since'].items():
        if since is not None:
            grace=since+state['config']['needs']['grace_hours'][resource]*3600
            if grace>start:
                result=min(result,grace)
    return result


def accrue(connection,state,seconds,now):
    if not enabled(state) or seconds<=0:
        return
    from game.economy import rates
    from game.simulation import _event
    from game.population import rebalance
    flow=rates(state);clock=copy.deepcopy(state['needs_clock']);start=now-seconds
    loss=0
    for resource,missing in shortages(state).items():
        if not missing:
            continue
        since=clock['since'][resource]
        if since is None:
            since=start;clock['since'][resource]=start
        after_grace=max(start,since+state['config']['needs']['grace_hours'][resource]*3600)
        deficit=max(0,1-flow[resource]['production']/flow[resource]['consumption'])
        loss+=max(0,now-after_grace)/3600*state['config']['needs']['hp_loss_per_hour'][resource]*deficit
    for citizen in state['citizens']:
        if not citizen.get('away') and loss:
            key=str(citizen['citizen_id']);clock['pending'][key]=clock['pending'].get(key,0)+loss
    tick=(now-state['recovery_clock']['anchor'])%state['config']['recovery']['tick_seconds']==0 or now==state['season']['ends_at']
    deaths=0
    if tick:
        for citizen in state['citizens']:
            damage=clock['pending'].get(str(citizen['citizen_id']),0)
            if not damage:
                continue
            row=connection.execute('SELECT current_hp,status FROM citizens WHERE citizen_id=?',(citizen['citizen_id'],)).fetchone()
            if row['status']!='alive':
                continue
            hp=max(0,row['current_hp']-damage)
            connection.execute('UPDATE citizens SET current_hp=? WHERE citizen_id=?',(hp,citizen['citizen_id']))
            if hp<=0:
                deaths+=1
                connection.execute("UPDATE citizens SET status='dead',died_at=?,death_cause='supply_shortage' WHERE citizen_id=?",(now,citizen['citizen_id']))
                connection.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='supply_shortage_death' WHERE citizen_id=? AND ended_at IS NULL",(now,citizen['citizen_id']))
                connection.execute("UPDATE citizen_settlement_history SET left_at=?,departure_reason='supply_shortage_death' WHERE citizen_id=? AND left_at IS NULL",(now,citizen['citizen_id']))
                _event(connection,state,'citizen_supply_death',now,{'citizen_id':citizen['citizen_id']})
        clock['pending'].clear()
    if clock!=state['needs_clock']:
        record(connection,state,now,clock)
    if deaths:
        current=read_state(connection)
        from game.combat import settings,update_morale
        rules=settings()['Morale'];delta=max(rules['citizen_death_event_cap'],deaths*rules['citizen_death'])
        for citizen in current['citizens']:
            update_morale(connection,citizen,delta,now,'supply_shortage_death')
        if not any(c['assignment']=='administrator' for c in current['citizens']):
            free=[c for c in current['citizens'] if c['assignment']=='unassigned' and not c.get('away') and c['current_hp']>0]
            if free:
                replacement=min(free,key=lambda c:(-c['level'],-c['xp'],c['joined_at'],c['citizen_id']))
                connection.execute("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,building_id,assigned_at) VALUES (?,?,'administrator',?,?)",(replacement['citizen_id'],state['settlement']['settlement_id'],state['buildings'][0]['building_id'],now))
                connection.execute('UPDATE citizens SET unemployed_since=NULL WHERE citizen_id=?',(replacement['citizen_id'],))
                _event(connection,state,'administrator_replaced',now,{'citizen_id':replacement['citizen_id']})
        rebalance(connection,read_state(connection),now)


def command(path,action,now,*,food='full',water='full'):
    from game.simulation import _advance
    with closing(connect_database(path)) as c,c:
        c.row_factory=sqlite3.Row;c.execute('BEGIN IMMEDIATE');state=read_state(c)
        from game.admin_controls import require_running
        require_running(c, state)
        if not state or state['season']['status']=='finished' or now>=state['season']['ends_at']:
            raise ValueError('This season is not active.')
        if now<state['settlement']['simulation_processed_at']:
            raise ValueError('The clock is earlier than the saved state.')
        _advance(c,state,now);state=read_state(c)
        at=state['season']['paused_at'] if state['season']['status']=='paused' else now
        if action=='enable':
            if enabled(state):
                return state
            if state['settlement']['status']=='suspended':
                from game.trading import supply_frozen
                if not supply_frozen(c,state):
                    raise ValueError('Administrative suspension cannot be lifted here.')
                from game.recovery import shift_clock
                seconds=now-state['settlement']['suspended_at']
                shift_clock(c,state,seconds,now)
                c.execute("UPDATE settlements SET status='active',suspended_at=NULL,simulation_processed_at=? WHERE settlement_id=?",(now,state['settlement']['settlement_id']))
                c.execute('UPDATE citizens SET unemployed_since=unemployed_since+?,homeless_since=homeless_since+? WHERE settlement_id=?',(seconds,seconds,state['settlement']['settlement_id']))
                state=read_state(c)
            if state['settlement']['status']!='active':
                raise ValueError('This settlement is not active.')
            from game.manufacturing import enable
            enable(c,state,at);state=read_state(c)
            record(c,state,at,{'since':{'food':None,'water':None},'pending':{}})
        elif action=='rations':
            if not enabled(state) or state['settlement']['status']!='active':
                raise ValueError('Enable supply consequences in an active settlement first.')
            if food not in ('full','reduced','emergency') or water not in ('full','reduced','emergency'):
                raise ValueError('Choose Full, Reduced or Emergency rations.')
            c.execute('UPDATE settlement_policies SET food_ration=?,water_ration=?,updated_at=? WHERE settlement_id=?',(food,water,at,state['settlement']['settlement_id']))
        else:
            raise ValueError('Unknown ration action.')
        synchronize(c,read_state(c),at)
        return read_state(c)


def panel(state,token):
    hidden=f'<input type="hidden" name="token" value="{escape(token,quote=True)}">'
    html='<section class="production-panel" id="needs"><h2>Supplies and rations</h2>'
    if not enabled(state):
        return html+f'<form method="post" action="/needs">{hidden}<input type="hidden" name="action" value="enable"><p>Replace shortage freezes with continuing production, ration controls, grace periods and health consequences. Existing frozen time is not punished retroactively.</p><button>Enable supply consequences</button></form></section>'
    html+='<p>Production and scavenging continue when supplies run out. Food shortage: 6-hour grace, then up to 2 HP/hour. Water shortage: 2-hour grace, then up to 4 HP/hour. Partial production reduces damage proportionally.</p>'
    html+=f'<form method="post" action="/needs">{hidden}<input type="hidden" name="action" value="rations">'
    for resource in ('food','water'):
        options=''.join(f'<option value="{mode}"{" selected" if state["policies"][resource+"_ration"]==mode else ""}>{mode.title()} — {rule["consumption"]:g}/citizen/hour, {rule["morale"]:+g} morale</option>' for mode,rule in state['config']['needs']['rations'][resource].items())
        html+=f'<label>{resource.title()} rations <select name="{resource}">{options}</select></label>'
    html+='<button>Set rations</button></form><p>Ration morale is a current modifier and ends when full rations return. Health loss stops as soon as supply meets demand. Natural healing needs both Food and Water.</p>'
    for resource,missing in shortages(state).items():
        html+=f'<p>{resource.title()}: '+('shortage; improve production, scavenge, trade or reduce rations.' if missing else 'needs met.')+'</p>'
    return html+'</section>'

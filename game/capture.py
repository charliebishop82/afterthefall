"""Approved population-capture prototype; integration occurs at next UTC rollover."""
import random
import json
from game.settlement import account_scope, read_state


def rules():
    from game.expansion import config
    return config()['prototype']


def workbook(key):
    from game.expansion import config
    return config()['settings']['Combat Raids'][key]


def choose(candidates, chance, rng, cap=None):
    selected=[]
    for citizen in candidates:
        if cap is not None and len(selected)>=cap:break
        if rng.random()<chance:selected.append(citizen)
    return selected


def transfer(connection, old, new, citizen, attack, now):
    sid=new['settlement']['settlement_id'];cid=citizen['citizen_id']
    row=connection.execute("SELECT settlement_id,status,current_hp FROM citizens WHERE citizen_id=?",(cid,)).fetchone()
    if not row or row['settlement_id']!=old['settlement']['settlement_id'] or row['status']!='alive' or row['current_hp']<=0:
        return None
    connection.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='captured' WHERE citizen_id=? AND ended_at IS NULL",(now,cid))
    connection.execute("UPDATE citizen_settlement_history SET left_at=?,departure_reason='captured' WHERE citizen_id=? AND left_at IS NULL",(now,cid))
    connection.execute("UPDATE citizens SET settlement_id=?,morale=?,integrated=0,unemployed_since=?,homeless_since=NULL WHERE citizen_id=?",(sid,rules()['captured_morale'],now,cid))
    connection.execute("INSERT INTO citizen_settlement_history(citizen_id,settlement_id,joined_at,arrival_reason,related_attack_id) VALUES (?,?,?,'captured',?)",(cid,sid,now,attack['attack_id']))
    connection.execute("UPDATE attack_citizens SET outcome='captured' WHERE attack_id=? AND citizen_id=?",(attack['attack_id'],cid))
    from game.simulation import _event
    result=dict(citizen_id=cid,name=citizen['name'],from_settlement=old['settlement']['settlement_id'],to_settlement=sid)
    _event(connection,new,'citizen_captured',now,{**result,'attack_id':attack['attack_id']})
    return result


def resolve(connection, attack, one, two, result, raider_ids, defender_ids, now, rng):
    if not one.get('expansion'):return []
    with account_scope(one['settlement']['account_id']):one=read_state(connection)
    with account_scope(two['settlement']['account_id']):two=read_state(connection)
    raiders=[c for c in one['citizens'] if c['citizen_id'] in raider_ids and c['current_hp']>0]
    if result=='attacker_win' and raiders:
        focused=attack['raid_objective']=='population'
        candidates=[c for c in two['citizens'] if not c.get('away') and c['current_hp']>0 and (focused or c['citizen_id'] in defender_ids)]
        selected=choose(candidates,rules()['focused_capture_chance'] if focused else workbook('successful_raid_capture_chance')/100,rng,rules()['focused_capture_cap'])
        old,new=two,one
    elif result=='defender_win':
        selected=choose(raiders,workbook('failed_raid_capture_chance')/100,rng);old,new=one,two
    else:return []
    captured=[transfer(connection,old,new,c,attack,now) for c in selected]
    from game.consequences import replace_admin
    from game.population import rebalance
    for owner in (one,two):
        with account_scope(owner['settlement']['account_id']):
            replace_admin(connection,read_state(connection),now)
            rebalance(connection,read_state(connection),now)
    return [row for row in captured if row]


def daily(connection, state, now):
    if not state.get('expansion'):return False
    pending=[c for c in state['citizens'] if not c['integrated'] and c['joined_at']//86400<now//86400]
    deferred=connection.execute("SELECT event_data FROM game_events WHERE settlement_id=? AND event_type='captured_integration_deferred' ORDER BY event_id DESC LIMIT 1",(state['settlement']['settlement_id'],)).fetchone()
    if deferred:
        data=json.loads(deferred[0])
        if now<data['until']:pending=[c for c in pending if c['citizen_id'] not in data['citizens']]
    if not pending:return False
    rng=random.Random(f'{state["season"]["map_seed"]}:{state["settlement"]["settlement_id"]}:{now//86400}:capture')
    from game.consequences import depart
    from game.simulation import _event
    for citizen in pending:
        chance=rules()['captured_desertion_max_chance']*max(0,1-citizen['effective_morale']/rules()['captured_desertion_threshold'])
        roll=rng.random()
        audit={'citizen_id':citizen['citizen_id'],'morale':citizen['effective_morale'],'chance':chance,'roll':roll}
        if roll<chance:
            depart(connection,state,citizen,now,'deserted')
            _event(connection,state,'captured_citizen_deserted',now,audit)
        else:
            connection.execute('UPDATE citizens SET integrated=1 WHERE citizen_id=?',(citizen['citizen_id'],))
            _event(connection,state,'captured_citizen_integrated',now,audit)
    return True

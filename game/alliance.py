"""One-hop, finite allied hardware pools; selection is fair and deterministic."""
import math
from game.settlement import account_scope, read_state


def quotas(pools, fraction=.25):
    """Round each ally down separately, never pool fractional contributions."""
    return {sid:list(units)[:math.floor(len(units)*fraction)] for sid,units in pools.items()}


def evenly(pools, limit, offset=0):
    ids=sorted(pools)
    if ids:
        offset%=len(ids);ids=ids[offset:]+ids[:offset]
    chosen=[];index=0
    while len(chosen)<limit:
        added=False
        for sid in ids:
            if index<len(pools[sid]) and len(chosen)<limit:
                chosen.append((sid,pools[sid][index]));added=True
        if not added:break
        index+=1
    return chosen


def partners(connection, state, attacker, now):
    if not state.get('expansion'):
        return []
    sid=state['settlement']['settlement_id']
    rows=connection.execute('''SELECT DISTINCT s.settlement_id,s.account_id FROM treaties t JOIN settlements s
        ON s.settlement_id=CASE WHEN t.settlement_a_id=? THEN t.settlement_b_id ELSE t.settlement_a_id END
        JOIN accounts a ON a.account_id=s.account_id
        WHERE t.season_id=? AND (? IN (t.settlement_a_id,t.settlement_b_id))
        AND t.treaty_type IN ('mutual_defense','full_defense') AND t.status='active'
        AND t.effective_at<=? AND (t.expires_at IS NULL OR t.expires_at>?)
        AND s.settlement_id!=? AND s.status='active' AND a.is_active=1 ORDER BY s.settlement_id''',
        (sid,state['season']['season_id'],sid,now,now,attacker)).fetchall()
    from game.combat import state_at
    result=[]
    for row in rows:
        current=state_at(connection,row['settlement_id'],now)
        # Catch-up can suspend an initially active ally at a supply shortage.
        if current['settlement']['status']=='active':result.append(current)
    return result


def drones(allies, kind, attack_strength, local_strength, attack_id):
    from game.drones import ready,strength
    from game.combat import rule
    pools=quotas({s['settlement']['settlement_id']:ready(s,kind) for s in allies})
    owners={s['settlement']['settlement_id']:s for s in allies}
    selected=[];total=local_strength
    needed=attack_strength*(1+rule('defender_win_margin')/100)
    for sid,unit in evenly(pools,sum(map(len,pools.values())),attack_id):
        if total>=needed:break
        selected.append((owners[sid],dict(unit)));total+=strength(owners[sid],unit)
    return selected


def losses(connection, selected, percent, now, attack, phase):
    from game.drones import damage
    report=[]
    for state,unit in selected:
        with account_scope(state['settlement']['account_id']):
            results=damage(connection,state,[unit],percent,now,attack,'ally',phase)
        for item in results:item['settlement_id']=state['settlement']['settlement_id']
        report.extend(results)
    return report

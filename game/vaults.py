"""Credits remain one balance; allocations protect it without duplicating funds."""
import math
import json
from game.buildings import spec


def allocations(state):
    from game.economy import utilities
    available=max(0,state['resources']['credits']-state.get('reserved',{}).get('credits',0))
    status=utilities(state)['buildings'];result={}
    for building in state['buildings']:
        if building['building_type']!='vault' or building['status'] not in ('active','upgrading') or building['current_hp']<=0:continue
        protected=min(available,int(spec(state,building)['vault_capacity']))
        result[building['building_id']]={'allocated':protected,'protected':protected if not status[building['building_id']]['reason'] else 0}
        available-=protected
    return result


def ledger(connection, state, amount, now, reference, kind):
    if not amount:return
    sid=state['settlement']['settlement_id']
    connection.execute('UPDATE settlement_resources SET credits=credits+?,updated_at=? WHERE settlement_id=?',(amount,now,sid))
    balance=connection.execute('SELECT credits FROM settlement_resources WHERE settlement_id=?',(sid,)).fetchone()[0]
    connection.execute('''INSERT INTO credit_transactions(season_id,settlement_id,transfer_ref,transaction_type,amount,balance_after,occurred_at)
        VALUES (?,?,?,?,?,?,?)''',(state['season']['season_id'],sid,reference,kind,amount,balance,now))


def destroyed(connection, state, building_id, attack_id, now):
    sid=state['settlement']['settlement_id']
    previous=connection.execute("SELECT event_data FROM game_events WHERE settlement_id=? AND event_type='vault_attack_allocations' AND json_extract(event_data,'$.attack_id') IS ? ORDER BY event_id DESC LIMIT 1",(sid,attack_id)).fetchone() if attack_id is not None else None
    if previous:
        snapshot=json.loads(previous[0])['allocations']
    else:
        snapshot={str(k):v for k,v in allocations(state).items()}
        if attack_id is not None:
            from game.simulation import _event
            _event(connection,state,'vault_attack_allocations',now,{'attack_id':attack_id,'allocations':snapshot})
    allocation=snapshot.get(str(building_id),{}).get('allocated',0)
    from game.expansion import config
    rules=config()['settings']['Economy Diplomacy']
    lost=math.floor(allocation*rules['vault_destroy_lost']/100)
    exposed=math.floor(allocation*rules['vault_destroy_capturable']/100)
    ledger(connection,state,-lost,now,f'vault:{attack_id}:{building_id}','vault_credits_destroyed')
    return {'allocated':allocation,'lost':lost,'exposed':exposed}


def raid(connection, one, two, attack, now, exposed=0, focused=False):
    from game.expansion import config
    rules=config()['settings']['Economy Diplomacy']
    available=max(0,two['resources']['credits']-two.get('reserved',{}).get('credits',0))
    protected=sum(a['protected'] for a in allocations(two).values())
    exposed=min(available,max(0,exposed))
    ordinary=math.floor(max(0,available-protected-exposed)*rules['unprotected_credit_raid_pct']/100) if focused else 0
    taken=min(available,ordinary+exposed)
    reference=f'credit-raid:{attack["attack_id"]}'
    ledger(connection,two,-taken,now,reference,'credits_raided')
    ledger(connection,one,taken,now,reference,'credits_raided')
    return taken

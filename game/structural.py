"""Missile inventory, interception, local turrets and structural raid objectives."""
import json
from html import escape
from game.settlement import read_state,account_scope
from game.buildings import spec


def enabled(state):return 'structural' in state['config']


def enable(connection,state,now):
    if enabled(state):return
    from game.maintenance import enable as maintenance
    maintenance(connection,state,now)
    connection.execute("UPDATE seasons SET config_version='prototype_v12' WHERE season_id=?",(state['season']['season_id'],))
    from game.simulation import _event
    _event(connection,state,'prototype_config_enabled',now,{'from':state['season']['config_version'],'to':'prototype_v12'})


def ammunition(state,kind):
    if not enabled(state):return []
    from game.economy import utilities
    status=utilities(state)['buildings']
    homes={b['building_id'] for b in state['buildings'][1:] if b['status']=='active' and not status[b['building_id']]['reason']}
    return [i for i in state['inventory'] if i['unit_type']==kind and i['quantity']>0 and i['building_id'] in homes]


def reserve(connection,state,attack_id,quantity,now):
    left=quantity
    for i in ammunition(state,'missile'):
        count=min(left,i['quantity'])
        if not count:continue
        connection.execute('UPDATE military_inventory SET quantity=quantity-?,updated_at=? WHERE inventory_id=?',(count,now,i['inventory_id']))
        connection.execute("INSERT INTO attack_munitions(attack_id,inventory_id,participant_settlement_id,role,quantity) VALUES (?,?,?,'attacker',?)",(attack_id,i['inventory_id'],state['settlement']['settlement_id'],count))
        left-=count
    if left:raise ValueError('Not enough ready missiles.')


def recall(connection,attack,now):
    rows=connection.execute("SELECT am.*,i.building_id,i.unit_type FROM attack_munitions am JOIN military_inventory i USING(inventory_id) WHERE attack_id=? AND role='attacker'",(attack['attack_id'],)).fetchall()
    for row in rows:
        home=connection.execute("SELECT status FROM buildings WHERE building_id=?",(row['building_id'],)).fetchone()
        remaining=row['quantity']-row['consumed_quantity']
        if remaining and home['status'] in ('active','upgrading'):
            connection.execute('UPDATE military_inventory SET quantity=quantity+?,updated_at=? WHERE inventory_id=?',(remaining,now,row['inventory_id']))
        elif remaining:
            # No operational home survived. Record the lost ammunition, never resurrect a ruin.
            connection.execute('UPDATE attack_munitions SET consumed_quantity=quantity WHERE attack_munition_id=?',(row['attack_munition_id'],))


def turret_strength(state,kind,target=None):
    if not enabled(state):return 0
    from game.economy import utilities
    from game.ruins import distance
    target=target or state['buildings'][0];status=utilities(state)['buildings'];total=0
    for b in state['buildings']:
        if b['building_type']==kind and b['status']=='active' and not status[b['building_id']]['reason'] and distance(state,b,target)<=spec(state,b)['defense_radius']:
            total+=spec(state,b)['defense_strength']*b['current_hp']/spec(state,b)['hp']
    return total


def missiles(connection,attack,one,two,now,rng,allies=()):
    from game.combat import settings
    from game.ruins import hit,distance
    report={'launched':0,'intercepted':0,'hits':[],'interceptors':[]}
    if not enabled(one):return report
    from game.alliance import quotas,evenly
    ally_states={a['settlement']['settlement_id']:a for a in allies}
    pools=quotas({sid:[i for i in ammunition(a,'interceptor') for _ in range(i['quantity'])] for sid,a in ally_states.items()})
    ally_interceptors=iter(evenly(pools,sum(map(len,pools.values())),attack['attack_id']))
    rows=connection.execute("SELECT * FROM attack_munitions WHERE attack_id=? AND role='attacker'",(attack['attack_id'],)).fetchall()
    report['launched']=sum(r['quantity']-r['consumed_quantity'] for r in rows)
    for row in rows:
        for _ in range(row['quantity']-row['consumed_quantity']):
            connection.execute('UPDATE attack_munitions SET consumed_quantity=consumed_quantity+1 WHERE attack_munition_id=?',(row['attack_munition_id'],))
            current=read_state(connection)
            batteries=ammunition(current,'interceptor')
            stopped=False;owner=two;role='defender'
            if not batteries:
                contribution=next(ally_interceptors,None)
                if contribution:
                    sid,inventory=contribution;owner=ally_states[sid];role='ally';batteries=[inventory]
            # One available interceptor is expended per incoming missile.
            if batteries:
                i=batteries[0];b=next(b for b in owner['buildings'] if b['building_id']==i['building_id'])
                chance=settings()['Combat Raids'][('interceptor_base_success' if b['level']==1 else f'interceptor_l{b["level"]}_success')]/100
                roll=rng.random();stopped=roll<chance
                connection.execute('UPDATE military_inventory SET quantity=quantity-1,updated_at=? WHERE inventory_id=?',(now,i['inventory_id']))
                connection.execute("INSERT INTO attack_munitions(attack_id,inventory_id,participant_settlement_id,role,quantity,consumed_quantity) VALUES (?,?,?,?,1,1) ON CONFLICT(attack_id,inventory_id) DO UPDATE SET quantity=quantity+1,consumed_quantity=consumed_quantity+1",(attack['attack_id'],i['inventory_id'],owner['settlement']['settlement_id'],role))
                report['interceptors'].append({'settlement_id':owner['settlement']['settlement_id'],'building_id':b['building_id'],'chance':chance,'roll':roll,'success':stopped})
            if stopped:report['intercepted']+=1;continue
            current=read_state(connection)
            candidates=[b for b in current['buildings'] if b['status'] in ('active','construction','upgrading')]
            target=rng.choice(candidates)
            splash=[b['building_id'] for b in candidates if b['building_id']!=target['building_id'] and distance(current,target,b)<=settings()['Combat Raids']['missile_splash_radius']]
            hit(connection,current,target['building_id'],settings()['Combat Raids']['missile_base_damage'],now,attack['attack_id'],report['hits'])
            for bid in splash:hit(connection,read_state(connection),bid,settings()['Combat Raids']['missile_splash_damage'],now,attack['attack_id'],report['hits'])
    return report


def damage_raid(connection,attack,one,two,attackers,offensive,result,now,rng,target=None):
    if not enabled(one):return []
    from game.combat import strength,settings
    from game.drones import strength as drone_strength
    from game.ruins import hit
    damage=sum(drone_strength(one,u) for u in offensive if u['current_hp']>0)*settings()['Combat Raids']['drone_damage_share']/100
    if attack['raid_objective']=='infrastructure' and result=='attacker_win':damage+=sum(strength(one,c) for c in attackers)*settings()['Combat Raids']['raid_damage_share']/100
    report=[]
    if damage:
        targets=[b for b in two['buildings'] if b['status'] in ('active','construction','upgrading')]
        hit(connection,two,(target if target and target['status'] in ('active','construction','upgrading') else rng.choice(targets))['building_id'],damage,now,attack['attack_id'],report)
    return report


def protect(connection,state,now):
    """Hostile Town-Hall-only shield, rearmed only after three functional buildings."""
    if not enabled(state):return
    from game.simulation import _event
    # Surviving sites and unstaffed/unpowered buildings still prevent protection.
    count=sum(b['status'] in ('active','construction','upgrading') for b in state['buildings'][1:])
    row=connection.execute("SELECT event_data FROM game_events WHERE settlement_id=? AND event_type='rebuilding_shield' ORDER BY event_id DESC LIMIT 1",(state['settlement']['settlement_id'],)).fetchone()
    if count or (row and not connection.execute("SELECT 1 FROM game_events WHERE settlement_id=? AND event_type='rebuilding_rearmed' AND occurred_at>?",(state['settlement']['settlement_id'],json.loads(row[0])['at'])).fetchone()):return
    if not connection.execute("SELECT 1 FROM building_state_events e JOIN buildings b USING(building_id) WHERE b.settlement_id=? AND e.event_type IN ('hostile_damage','hostile_destruction') AND e.occurred_at=?",(state['settlement']['settlement_id'],now)).fetchone():return
    until=now+int(state['config']['structural']['rebuild_hours']*3600)
    connection.execute("UPDATE settlements SET protection_until=?,protection_type='rebuilding' WHERE settlement_id=?",(until,state['settlement']['settlement_id']))
    _event(connection,state,'rebuilding_shield',now,{'at':now,'until':until})
    from game.combat import cancel
    for attack in connection.execute("SELECT * FROM attacks WHERE defender_settlement_id=? AND status='in_flight' AND resolves_at>?",(state['settlement']['settlement_id'],now)).fetchall():cancel(connection,attack,now,'Target entered rebuilding protection.')


def rearm(connection,state,now):
    if not enabled(state):return
    row=connection.execute("SELECT occurred_at FROM game_events WHERE settlement_id=? AND event_type='rebuilding_shield' ORDER BY event_id DESC LIMIT 1",(state['settlement']['settlement_id'],)).fetchone()
    if not row:return
    if connection.execute("SELECT 1 FROM game_events WHERE settlement_id=? AND event_type='rebuilding_rearmed' AND occurred_at>?",(state['settlement']['settlement_id'],row[0])).fetchone():return
    from game.economy import utilities
    status=utilities(state)['buildings']
    if sum(b['status']=='active' and not status[b['building_id']]['reason'] for b in state['buildings'][1:])>=state['config']['structural']['rebuild_rearm_buildings']:
        from game.simulation import _event
        _event(connection,state,'rebuilding_rearmed',now,{})


def panel(state,token):
    from game.building_views import form
    if not enabled(state):return '<section class="production-panel"><h2>Structural combat and recovery</h2><p>Enable missiles, interceptors, turrets, building damage and ruin salvage for this season.</p>'+form(token,'enable_structural','<button>Enable structural combat and recovery</button>')+'</section>'
    return '<section class="production-panel"><h2>Structural combat</h2><p>Missiles strike random buildings; interceptors defend automatically. Turrets defend locally and need power. Infrastructure raids damage buildings instead of taking resources. Drones can damage buildings after combat. The Town Hall survives attacks and retains its basic utility zones.</p></section>'

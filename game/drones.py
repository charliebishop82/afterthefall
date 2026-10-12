"""Finite drone deployment and the approved two-phase resource-raid prototype."""
from game.buildings import spec
from game.combat import rule


def ready(state,kind):
    if state['season']['config_version'] not in ('prototype_v10','prototype_v11','prototype_v12','prototype_v13'):return []
    from game.economy import utilities
    utility=utilities(state)
    homes={b['building_id'] for b in state['buildings'][1:] if b['status']=='active' and not utility['buildings'][b['building_id']]['reason']}
    return [u for u in state['units'] if u['unit_type']==kind and u['status']=='available' and u['current_hp']>0 and u['home_building_id'] in homes]


def strength(state,unit):
    kind=unit['unit_type'];s=state['config']['units'][kind]
    return s['strength']*max(rule('drone_hp_strength_floor')/100,min(1,unit['current_hp']/s['hp'])) if unit['current_hp']>0 else 0


def outcome(a,d):
    return 'attacker_win' if a>=d*(1+rule('attacker_win_margin')/100) else 'defender_win' if d>=a*(1+rule('defender_win_margin')/100) else 'contested'


def rate(result,attacking):
    return rule('contested_casualty_rate') if result=='contested' else rule('clean_win_casualty_rate') if (result=='attacker_win')==attacking else rule('clean_loss_casualty_rate')


def damage(connection,state,units,percent,now,attack,role,phase):
    results=[]
    for u in units:
        before=u['current_hp'];loss=state['config']['units'][u['unit_type']]['hp']*percent/100
        hp=max(0,before-loss);u['current_hp']=hp
        if hp>0 and phase=='raid' and role!='attacker':
            hp=return_home(connection,state,u,hp,now)
        pending=hp>0 and role=='attacker'
        status='destroyed' if hp<=0 else 'deployed' if pending else 'available'
        connection.execute('UPDATE military_units SET current_hp=?,status=?,destroyed_at=? WHERE unit_id=?',(hp,status,now if hp<=0 else None,u['unit_id']))
        connection.execute('''INSERT INTO attack_drones(attack_id,unit_id,participant_settlement_id,role,committed_at,released_at,outcome)
            VALUES (?,?,?,?,?,?,?) ON CONFLICT(attack_id,unit_id) DO UPDATE SET released_at=excluded.released_at,outcome=excluded.outcome''',(attack['attack_id'],u['unit_id'],state['settlement']['settlement_id'],role,now,None if pending else now,'destroyed' if hp<=0 else 'in_flight' if pending else 'returned'))
        results.append({'unit_id':u['unit_id'],'type':u['unit_type'],'hp_before':before,'hp_after':hp,'damage':loss,'outcome':'destroyed' if hp<=0 else 'survived' if pending else 'returned','phase':phase})
    return results


def finish_return(connection,state,units,now,attack):
    """Deliver earned rewards before checking surviving attackers' home slots."""
    results=[]
    for unit in units:
        before=unit['current_hp']
        if before<=0:continue
        hp=return_home(connection,state,unit,before,now)
        outcome='returned' if hp>0 else 'destroyed_no_home'
        connection.execute('UPDATE military_units SET current_hp=?,status=?,destroyed_at=? WHERE unit_id=?',(hp,'available' if hp>0 else 'destroyed',None if hp>0 else now,unit['unit_id']))
        connection.execute('UPDATE attack_drones SET released_at=?,outcome=? WHERE attack_id=? AND unit_id=?',(now,outcome,attack['attack_id'],unit['unit_id']))
        results.append({'unit_id':unit['unit_id'],'hp_before':before,'hp_after':hp,'home_building_id':unit['home_building_id'],'outcome':outcome})
    return results


def aerial(connection,attack,one,two,now,rng,allies=()):
    ids={r[0] for r in connection.execute("SELECT unit_id FROM attack_drones WHERE attack_id=? AND role='attacker' AND released_at IS NULL",(attack['attack_id'],))}
    offensive=[dict(u) for u in one['units'] if u['unit_id'] in ids and u['status']=='deployed' and u['current_hp']>0]
    air=[dict(u) for u in ready(two,'air_defense_drone')] if offensive else []
    report={'attackers':[],'defenders':[],'result':None,'attack_strength':0,'defense_strength':0}
    from game.structural import turret_strength
    turret=turret_strength(two,'anti_air_turret',two.get('combat_target')) if offensive else 0
    from game import alliance
    selected=alliance.drones(allies,'air_defense_drone',sum(strength(one,u) for u in offensive),sum(strength(two,u) for u in air)+turret,attack['attack_id']) if offensive else []
    if air or turret or selected:
        variance=rule('combat_random_variance')/100
        a=sum(strength(one,u) for u in offensive)*rng.uniform(1-variance,1+variance)
        d=(sum(strength(two,u) for u in air)+turret+sum(strength(owner,u) for owner,u in selected))*rng.uniform(1-variance,1+variance)
        result=outcome(a,d)
        report.update(result=result,attack_strength=a,defense_strength=d)
        report['attackers']=damage(connection,one,offensive,rate(result,True),now,attack,'attacker','air')
        report['allies']=alliance.losses(connection,selected,rate(result,False),now,attack,'air')
        report['defenders']=damage(connection,two,air,rate(result,False),now,attack,'defender','air')
    return [u for u in offensive if u['current_hp']>0],report


def recall(connection,attack,now):
    rows=connection.execute("SELECT unit_id FROM attack_drones WHERE attack_id=? AND role='attacker' AND released_at IS NULL",(attack['attack_id'],)).fetchall()
    for row in rows:
        from game.settlement import account_scope,read_state
        owner=connection.execute('SELECT s.account_id FROM military_units u JOIN settlements s USING(settlement_id) WHERE unit_id=?',(row[0],)).fetchone()
        with account_scope(owner[0]):
            state=read_state(connection);u=next(u for u in state['units'] if u['unit_id']==row[0])
            hp=return_home(connection,state,u,u['current_hp'],now)
            connection.execute("UPDATE military_units SET status=?,current_hp=?,destroyed_at=? WHERE unit_id=? AND status='deployed'",('available' if hp>0 else 'destroyed',hp,None if hp>0 else now,row[0]))
    connection.execute("UPDATE attack_drones SET released_at=?,outcome='recalled' WHERE attack_id=? AND released_at IS NULL",(now,attack['attack_id']))


def return_home(connection,state,unit,hp,now):
    """Keep a surviving home; relocate to a free compatible home after its loss."""
    if 'structural' not in state['config']:return hp
    home=next((b for b in state['buildings'] if b['building_id']==unit['home_building_id']),None)
    if home and home['status'] in ('active','upgrading'):return hp
    from game.manufacturing import home_for
    from game.settlement import account_scope,read_state
    with account_scope(state['settlement']['account_id']):
        destination=home_for(read_state(connection),unit['unit_type'])
    if destination:
        unit['home_building_id']=destination['building_id']
        connection.execute('UPDATE military_units SET home_building_id=? WHERE unit_id=?',(destination['building_id'],unit['unit_id']))
        return hp
    unit['current_hp']=0
    return 0

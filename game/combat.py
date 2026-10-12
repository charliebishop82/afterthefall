"""Citizen, drone and missile raids, war warnings and private battle reports."""
from contextlib import closing
from contextvars import ContextVar
from functools import lru_cache
from html import escape
import hashlib
import json
from pathlib import Path
import random
import secrets
import sqlite3

from database.create_database import connect_database
from game.settlement import CURRENT_ACCOUNT, account_scope, read_state

RESOLVING = ContextVar('resolving_attacks', default=False)
PHYSICAL = ('food','water','scrap','metal','electronics')
OBJECTIVES = PHYSICAL + ('balanced',)


@lru_cache(maxsize=1)
def settings():
    return json.loads((Path(__file__).resolve().parents[1]/'config/combat_v1.json').read_text())['settings']


def rule(key): return settings()['Combat Raids'][key]


def home(state): return [c for c in state['citizens'] if not c.get('away')]


def daily(connection, state, now):
    """Apply a reached UTC rollover; never add population before catch-up reaches it."""
    s=state['settlement']; day=now//86400*86400
    previous=s['last_rollover_at'] if s['last_rollover_at'] is not None else s['created_at']//86400*86400
    if CURRENT_ACCOUNT.get() is None or day<=previous or state['season']['status'] not in ('active','finalizing') or s['status']!='active' or now>=state['season']['ends_at']:
        return False
    connection.execute('UPDATE settlements SET last_rollover_at=?,attacks_remaining=? WHERE settlement_id=?',
                       (day,int(settings()['Citizen Economy']['attack_limit_daily']),s['settlement_id']))
    # Combat can reduce population below the floor. Count all living citizens,
    # including deployed citizens, so a raid cannot generate free replacements.
    from game.population import generated_name
    rng=random.Random(f'{state["season"]["map_seed"]}:{s["settlement_id"]}:{day}:floor')
    for i in range(max(0,int(rule('raid_home_population_min'))-len(state['citizens']))):
        cid=connection.execute('''INSERT INTO citizens
            (settlement_id,original_settlement_id,name,sex,level,current_hp,morale,status,unemployed_since,created_at)
            VALUES (?,?,?,?,1,?,?,'alive',?,?)''',
            (s['settlement_id'],s['settlement_id'],generated_name(connection,s['settlement_id'],rng),rng.choice(('male','female')),state['config']['citizen_hp'],state['config']['citizen_morale'],now,now)).lastrowid
        connection.execute("INSERT INTO citizen_settlement_history(citizen_id,settlement_id,joined_at,arrival_reason) VALUES (?,?,?,'midnight_population_floor')",(cid,s['settlement_id'],now))
        connection.execute('INSERT INTO citizen_level_history(citizen_id,level,xp_total,reached_at) VALUES (?,1,0,?)',(cid,now))
    from game.simulation import _event
    _event(connection,state,'combat_daily_rollover',now,{'day':day})
    return True


def maximum_hp(state,c):
    # V1 saves predate the simulation section. Match the existing simulation's
    # V2 fallback without activating features or changing the saved profile.
    from game.settlement import load_config
    simulation=state['config'].get('simulation') or load_config('prototype_v2')['simulation']
    return state['config']['citizen_hp']+(c['level']-1)*simulation['hp_per_level']


def strength(state,c):
    if c['current_hp']<=0:return 0
    morale=c.get('effective_morale',c['morale']); thresholds=settings()['Morale']
    modifier=rule('morale_combat_low') if morale<thresholds['morale_low_threshold'] else rule('morale_combat_high') if morale>=thresholds['morale_high_threshold'] else rule('morale_combat_normal')
    return (rule('citizen_base_combat')+(c['level']-1)*rule('citizen_combat_per_level'))*max(rule('citizen_hp_combat_floor')/100,min(1,c['current_hp']/maximum_hp(state,c)))*modifier/100


def blocked(connection,one,two,now):
    a,b=sorted((one['settlement']['settlement_id'],two['settlement']['settlement_id']))
    return bool(connection.execute('''SELECT 1 FROM treaties WHERE settlement_a_id=? AND settlement_b_id=?
        AND treaty_type IN ('peace','non_aggression','nonaggression')
        AND ((status='active' AND (expires_at IS NULL OR expires_at>?)) OR (status='cancelled' AND cooldown_until>?))''',(a,b,now,now)).fetchone())


def war(connection,one,two,now):
    a,b=sorted((one['settlement']['settlement_id'],two['settlement']['settlement_id']))
    return connection.execute("SELECT * FROM treaties WHERE settlement_a_id=? AND settlement_b_id=? AND treaty_type='war' AND status='active' AND (expires_at IS NULL OR expires_at>?) ORDER BY treaty_id DESC LIMIT 1",(a,b,now)).fetchone()


def eligible(state,now):
    if not state or state['settlement']['status']!='active' or state['season']['status'] not in ('active','finalizing') or now>=state['season']['ends_at']:
        raise ValueError('Conflict needs active settlements in an active season.')
    if now<state['settlement']['simulation_processed_at']:raise ValueError('The clock is earlier than the saved state.')


def command(path,action,now,*,target_id=None,citizen_ids=None,objective='balanced',drone_ids=None,missile_count=0):
    if CURRENT_ACCOUNT.get() is None:raise ValueError('Log in first.')
    if action not in ('declare','launch'):raise ValueError('Unknown conflict action.')
    from game.trading import player_state
    from game.simulation import _event
    with closing(connect_database(path)) as connection,connection:
        connection.row_factory=sqlite3.Row;connection.execute('BEGIN IMMEDIATE')
        state=read_state(connection)
        if not state:raise ValueError('Create a settlement first.')
        sid=state['settlement']['settlement_id']
        if type(target_id) is not int or target_id==sid:raise ValueError('Choose another settlement.')
        state=player_state(connection,sid,now);other=player_state(connection,target_id,now)
        # Resolving a due raid while reading the target may alter our own state.
        state=read_state(connection)
        eligible(state,now);eligible(other,now)
        if state['season']['season_id']!=other['season']['season_id']:raise ValueError('Choose a settlement in this season.')
        if now>=state['season']['finalization_at'] or state['season']['status']=='finalizing':raise ValueError('New conflict actions are closed during the final three hours.')
        if blocked(connection,state,other,now):raise ValueError('A treaty or treaty cooldown blocks hostile actions.')
        a,b=sorted((sid,target_id));declaration=war(connection,state,other,now)
        if action=='declare':
            from game.diplomacy import war_cooldown
            if war_cooldown(connection,sid,target_id,now):raise ValueError('Peace-to-war cooldown is still active.')
            if declaration:raise ValueError('War is already declared between these settlements.')
            warning=int(settings()['Economy Diplomacy']['war_warning']*3600)
            tid=connection.execute('''INSERT INTO treaties(season_id,settlement_a_id,settlement_b_id,treaty_type,status,proposer_settlement_id,proposed_at,accepted_at,effective_at)
                VALUES (?,?,?,'war','active',?,?,?,?)''',(state['season']['season_id'],a,b,sid,now,now,now+warning)).lastrowid
            for owner in (state,other):
                connection.execute("INSERT INTO notifications(account_id,season_id,notification_type,message,created_at,related_type,related_id) VALUES (?,?,'war_declared',?,?,'treaty',?)",(owner['settlement']['account_id'],owner['season']['season_id'],f'War declared between {state["settlement"]["settlement_name"]} and {other["settlement"]["settlement_name"]}. Attacks unlock after the one-hour warning.',now,tid))
                _event(connection,owner,'war_declared',now,{'treaty_id':tid})
            from game.social import news
            news(connection,state['season']['season_id'],'war_declared',f'War declared between {state["settlement"]["settlement_name"]} and {other["settlement"]["settlement_name"]}.',now)
            return tid
        if not declaration or now<declaration['effective_at']:raise ValueError('Declare war and wait for the one-hour warning to end.')
        if (other['settlement']['protection_until'] or 0)>now:raise ValueError('That settlement is protected.')
        from game.structural import enabled as structural_enabled,ammunition,reserve
        objectives=OBJECTIVES+(('population','credits') if state.get('expansion') else ())+(('infrastructure',) if structural_enabled(state) else ())
        if objective not in objectives:raise ValueError('Choose an available raid objective.')
        if type(missile_count) is not int or missile_count<0 or missile_count>sum(i['quantity'] for i in ammunition(state,'missile')):raise ValueError('Choose an available whole number of missiles.')
        citizen_ids=[] if citizen_ids is None else citizen_ids
        drone_ids=[] if drone_ids is None else drone_ids
        if not isinstance(citizen_ids,list) or any(type(cid) is not int for cid in citizen_ids) or len(set(citizen_ids))!=len(citizen_ids):raise ValueError('Select distinct citizens from your settlement.')
        if not isinstance(drone_ids,list) or any(type(uid) is not int for uid in drone_ids) or len(set(drone_ids))!=len(drone_ids):raise ValueError('Select distinct offensive drones.')
        if objective=='population' and not citizen_ids:raise ValueError('Population raids require citizen raiders.')
        if not citizen_ids and not drone_ids and not missile_count:raise ValueError('Select citizens, offensive drones or ready missiles for the raid.')
        from game.drones import ready
        available_drones={u['unit_id']:u for u in ready(state,'offensive_drone')}
        if any(uid not in available_drones for uid in drone_ids):raise ValueError('Choose your available offensive drones with operational home hangars.')
        candidates={c['citizen_id']:c for c in home(state)}
        if len(candidates)-len(citizen_ids)<rule('raid_home_population_min'):raise ValueError('At least six citizens must remain physically at home. Rescue more survivors before raiding.')
        for cid in citizen_ids:
            c=candidates.get(cid)
            if not c or c['assignment'] not in (('unassigned','administrator') if state['season']['config_version']=='prototype_v13' else ('unassigned',)):raise ValueError('Raiders must be your own unassigned citizens at home.')
            if c['current_hp']/maximum_hp(state,c)<rule('citizen_low_hp_raid_threshold')/100:raise ValueError('Raiders need at least 25% of maximum health.')
            if not connection.execute('SELECT integrated FROM citizens WHERE citizen_id=?',(cid,)).fetchone()[0]:raise ValueError('This citizen is not integrated yet.')
        if state['settlement']['attacks_remaining']<=0:raise ValueError('No attack allowances remain until midnight UTC.')
        arrives=now+int(rule('attack_travel_time')*60)
        aid=connection.execute('''INSERT INTO attacks(season_id,attacker_settlement_id,defender_settlement_id,launched_at,resolves_at,status,raid_objective,random_seed)
            VALUES (?,?,?,?,?,'in_flight',?,?)''',(state['season']['season_id'],sid,target_id,now,arrives,objective,secrets.token_hex(32))).lastrowid
        if missile_count:reserve(connection,state,aid,missile_count,now)
        for cid in citizen_ids:
            connection.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='raid_deployment' WHERE citizen_id=? AND assignment_type='administrator' AND ended_at IS NULL",(now,cid))
        if citizen_ids:
            connection.execute('UPDATE citizens SET unemployed_since=NULL WHERE citizen_id IN ('+','.join('?' for _ in citizen_ids)+')',citizen_ids)
        for cid in citizen_ids:connection.execute("INSERT INTO attack_citizens(attack_id,citizen_id,participant_settlement_id,role,committed_at) VALUES (?,?,?,'attacker',?)",(aid,cid,sid,now))
        for uid in drone_ids:
            connection.execute("INSERT INTO attack_drones(attack_id,unit_id,participant_settlement_id,role,committed_at) VALUES (?,?,?,'attacker',?)",(aid,uid,sid,now))
            connection.execute("UPDATE military_units SET status='deployed' WHERE unit_id=?",(uid,))
        connection.execute('UPDATE settlements SET attacks_remaining=attacks_remaining-1,has_attacked=1,protection_until=?,protection_type=NULL WHERE settlement_id=?',(now,sid))
        if state['season']['config_version']=='prototype_v13':
            from game.consequences import replace_admin
            replace_admin(connection,read_state(connection),now)
        _event(connection,state,'citizen_raid_launched',now,{'attack_id':aid})
        _event(connection,other,'citizen_raid_incoming',now,{'attack_id':aid,'resolves_at':arrives})
        return aid


def state_at(connection,sid,now):
    row=connection.execute('SELECT account_id FROM settlements WHERE settlement_id=?',(sid,)).fetchone()
    with account_scope(row['account_id']):
        from game.simulation import _advance
        _advance(connection,read_state(connection),now)
        state=read_state(connection)
        if daily(connection,state,now):state=read_state(connection)
        return state


def cancel(connection,attack,now,reason):
    status=connection.execute('SELECT status FROM attacks WHERE attack_id=?',(attack['attack_id'],)).fetchone()
    if not status or status[0]!='in_flight':return
    from game.drones import recall
    recall(connection,attack,now)
    from game.structural import recall as recall_missiles
    recall_missiles(connection,attack,now)
    connection.execute("UPDATE attack_citizens SET released_at=?,outcome='recalled' WHERE attack_id=? AND released_at IS NULL",(now,attack['attack_id']))
    connection.execute("UPDATE attacks SET status='cancelled',resolved_at=?,cancel_reason=?,allowance_refunded=1 WHERE attack_id=?",(now,reason,attack['attack_id']))
    connection.execute('UPDATE settlements SET attacks_remaining=min(?,attacks_remaining+1) WHERE settlement_id=?',(int(settings()['Citizen Economy']['attack_limit_daily']),attack['attacker_settlement_id']))


def update_morale(connection,c,delta,now,reason):
    after=min(100,max(0,c['morale']+delta))
    connection.execute('UPDATE citizens SET morale=? WHERE citizen_id=?',(after,c['citizen_id']))
    connection.execute('INSERT INTO citizen_morale_events(citizen_id,morale_before,morale_after,reason,occurred_at) VALUES (?,?,?,?,?)',(c['citizen_id'],c['morale'],after,reason,now))


def participants_result(connection,state,citizens,rate,victory,now,attack):
    outcomes=[];deaths=0
    for c in citizens:
        damage=maximum_hp(state,c)*rate/100;hp=max(0,c['current_hp']-damage)
        connection.execute('UPDATE citizens SET current_hp=? WHERE citizen_id=?',(hp,c['citizen_id']))
        if hp<=0:
            deaths+=1
            connection.execute("UPDATE citizens SET status='dead',died_at=?,death_cause='citizen_raid',death_related_id=? WHERE citizen_id=?",(now,attack['attack_id'],c['citizen_id']))
            connection.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='combat_death' WHERE citizen_id=? AND ended_at IS NULL",(now,c['citizen_id']))
            connection.execute("UPDATE citizen_settlement_history SET left_at=?,departure_reason='combat_death' WHERE citizen_id=? AND left_at IS NULL",(now,c['citizen_id']))
        else:
            xp=c['xp']+settings()['Citizen Economy']['combat_participation_xp']+(settings()['Citizen Economy']['combat_victory_bonus_xp'] if victory else 0)
            level=max(c['level'],sum(xp+1e-9>=t for t in state['config']['progression']['thresholds']))
            connection.execute('UPDATE citizens SET xp=?,level=? WHERE citizen_id=?',(xp,level,c['citizen_id']))
            connection.execute("INSERT INTO citizen_xp_events(citizen_id,amount,xp_total,reason,occurred_at) VALUES (?,?,?,'combat',?)",(c['citizen_id'],xp-c['xp'],xp,now))
            for reached in range(c['level']+1,level+1):connection.execute('INSERT INTO citizen_level_history(citizen_id,level,xp_total,reached_at) VALUES (?,?,?,?)',(c['citizen_id'],reached,xp,now))
        outcomes.append({'citizen_id':c['citizen_id'],'name':c['name'],'hp_before':c['current_hp'],'damage':damage,'hp_after':hp,'outcome':'dead' if hp<=0 else 'returned'})
    return outcomes,deaths


def take_loot(connection,one,two,raiders,objective,now,drone_capacity=0):
    from game.trading import available
    from game.economy import storage
    capacity=sum(rule('citizen_loot_capacity')+(c['level']-1)*rule('citizen_loot_level_bonus') for c in raiders)
    capacity+=drone_capacity
    pools={r:available(two,r) for r in PHYSICAL};taken=dict.fromkeys(PHYSICAL,0.0)
    if objective=='balanced':
        total=sum(pools.values());ratio=min(1,capacity/total) if total else 0
        taken={r:pools[r]*ratio for r in PHYSICAL}
    else:
        for r in (objective,)+tuple(r for r in PHYSICAL if r!=objective):
            taken[r]=min(pools[r],capacity);capacity-=taken[r]
    limits=storage(one);materials=('scrap','metal','electronics')
    free={r:max(0,limits[r]-one['resources'][r]) for r in ('food','water')}
    free['material']=max(0,limits['material']-sum(one['resources'][r] for r in materials))
    deposited={};order=PHYSICAL if objective=='balanced' else (objective,)+tuple(r for r in PHYSICAL if r!=objective)
    for r in order:
        pool=r if r in free else 'material';deposited[r]=min(taken[r],free[pool]);free[pool]-=deposited[r]
    for state,change in [(one,deposited),(two,{r:-taken[r] for r in PHYSICAL})]:
        connection.execute('''UPDATE settlement_resources SET food=food+?,water=water+?,scrap=scrap+?,metal=metal+?,electronics=electronics+?,updated_at=? WHERE settlement_id=?''',tuple(change[r] for r in PHYSICAL)+(now,state['settlement']['settlement_id']))
    return {'taken':taken,'deposited':deposited,'lost':{r:taken[r]-deposited[r] for r in PHYSICAL}}


def resolve(connection,attack,now):
    status=connection.execute('SELECT status FROM attacks WHERE attack_id=?',(attack['attack_id'],)).fetchone()
    if not status or status[0]!='in_flight':return
    one=state_at(connection,attack['attacker_settlement_id'],now);two=state_at(connection,attack['defender_settlement_id'],now)
    active=all(connection.execute('SELECT is_active FROM accounts WHERE account_id=?',(s['settlement']['account_id'],)).fetchone()[0] for s in (one,two))
    if not active or any(s['settlement']['status']!='active' or s['season']['status'] not in ('active','finalizing') for s in (one,two)) or (two['settlement']['protection_until'] or 0)>now or blocked(connection,one,two,now) or not war(connection,one,two,now):
        cancel(connection,attack,now,'Participants, protection or diplomacy no longer permit the raid.');return
    rng=random.Random(attack['random_seed']);variance=rule('combat_random_variance')/100
    rolls=[rng.uniform(1-variance,1+variance) for _ in range(2)]
    from game import structural
    from game import alliance
    allies=alliance.partners(connection,two,one['settlement']['settlement_id'],now)
    with account_scope(two['settlement']['account_id']):
        missile_report=structural.missiles(connection,attack,one,two,now,rng,allies)
        two=read_state(connection)
    target=two['buildings'][0]
    if structural.enabled(one) and attack['raid_objective']=='infrastructure':
        target=rng.choice([b for b in two['buildings'] if b['status'] in ('active','construction','upgrading')])
    two['combat_target']=target
    ids={r[0] for r in connection.execute("SELECT citizen_id FROM attack_citizens WHERE attack_id=? AND role='attacker' AND released_at IS NULL",(attack['attack_id'],))}
    attackers=[c for c in one['citizens'] if c['citizen_id'] in ids and c['current_hp']>0]
    from game.support import enabled as support_enabled,guards,defense_bonus
    guard_ids={c['citizen_id'] for c in guards(two)}
    defenders=[c for c in home(two) if c['current_hp']>0 and (c['assignment'] in ('unassigned','patrol') or c['assignment']=='defender' and (not support_enabled(two) or c['citizen_id'] in guard_ids))]
    committed=connection.execute("SELECT 1 FROM attack_drones WHERE attack_id=? AND role='attacker' AND released_at IS NULL",(attack['attack_id'],)).fetchone()
    if not attackers and not committed and not missile_report['launched']:cancel(connection,attack,now,'No living raiders remain.');return
    if structural.enabled(one) and attackers:
        defenders += [c for c in home(two) if c['building_id']==target['building_id'] and c['current_hp']>0 and c not in defenders]
    from game import drones
    offensive,air_report=drones.aerial(connection,attack,one,two,now,rng,allies)
    ground=[dict(u) for u in drones.ready(two,'ground_defense_drone')] if attackers else []
    if not attackers and not offensive:defenders=[];ground=[]
    attack_strength=(sum(strength(one,c) for c in attackers)+sum(drones.strength(one,u) for u in offensive))*rolls[0]
    defense_strength=(sum(strength(two,c)*(1+rule('patrol_strength_bonus')/100 if c['assignment']=='patrol' else 1) for c in defenders)+sum(drones.strength(two,u) for u in ground)+(defense_bonus(two) if attackers or not structural.enabled(one) else 0)+(structural.turret_strength(two,'automated_turret',target) if attackers else 0))*rolls[1]
    allied_ground=alliance.drones(allies,'ground_defense_drone',attack_strength/rolls[1],defense_strength/rolls[1],attack['attack_id']) if attackers else []
    defense_strength+=sum(drones.strength(owner,unit) for owner,unit in allied_ground)*rolls[1]
    result='attacker_win' if attack_strength>=defense_strength*(1+rule('attacker_win_margin')/100) else 'defender_win' if defense_strength>=attack_strength*(1+rule('defender_win_margin')/100) else 'contested'
    if attack_strength<=0:result='attacker_win' if any(h['hp_before']>h['hp_after'] or h['destroyed'] for h in missile_report['hits']) else 'defender_win'
    drone_attack_results=drones.damage(connection,one,offensive,drones.rate(result,True),now,attack,'attacker','raid')
    allied_losses=alliance.losses(connection,allied_ground,drones.rate(result,False),now,attack,'raid')
    drone_defense_results=drones.damage(connection,two,ground,drones.rate(result,False),now,attack,'defender','raid')
    ar=rule('contested_casualty_rate') if result=='contested' else rule('clean_win_casualty_rate') if result=='attacker_win' else rule('clean_loss_casualty_rate')
    dr=rule('contested_casualty_rate') if result=='contested' else rule('clean_win_casualty_rate') if result=='defender_win' else rule('clean_loss_casualty_rate')
    a_results,a_deaths=participants_result(connection,one,attackers,ar,result=='attacker_win',now,attack)
    d_results,d_deaths=participants_result(connection,two,defenders,dr,result=='defender_win',now,attack)
    for outcome in a_results:
        connection.execute('UPDATE attack_citizens SET released_at=?,outcome=? WHERE attack_id=? AND citizen_id=?',(now,outcome['outcome'],attack['attack_id'],outcome['citizen_id']))
    for outcome in d_results:
        connection.execute("INSERT INTO attack_citizens(attack_id,citizen_id,participant_settlement_id,role,committed_at,released_at,outcome) VALUES (?,?,?,'defender',?,?,?)",(attack['attack_id'],outcome['citizen_id'],two['settlement']['settlement_id'],now,now,outcome['outcome']))
    d_deaths+=len({i['citizen_id'] for h in missile_report['hits'] for i in h['injuries'] if i['hp_after']<=0})
    morale=settings()['Morale']
    for owner,deaths in [(one,a_deaths),(two,d_deaths)]:
        for c in owner['citizens']:
            if not connection.execute("SELECT 1 FROM citizens WHERE citizen_id=? AND status='alive'",(c['citizen_id'],)).fetchone():continue
            delta=max(morale['citizen_death_event_cap'],deaths*morale['citizen_death'])
            if owner is one and c['citizen_id'] in ids:delta+=morale['successful_raid'] if result=='attacker_win' else morale['failed_raid'] if result=='defender_win' else 0
            if owner is two:delta+=morale['recent_attack_loss'] if result=='attacker_win' else morale['recent_attack_win'] if result=='defender_win' else 0
            if delta:update_morale(connection,c,delta,now,'citizen_raid')
    one=state_at(connection,one['settlement']['settlement_id'],now);two=state_at(connection,two['settlement']['settlement_id'],now)
    survivors=[c for c in one['citizens'] if c['citizen_id'] in ids and c['current_hp']>0]
    loot={'taken':{},'deposited':{},'lost':{}}
    returning=[u for u in offensive if u['current_hp']>0]
    if attack['raid_objective'] not in ('infrastructure','population','credits') and result=='attacker_win' and sum(strength(one,c) for c in survivors)+sum(drones.strength(one,u) for u in returning)>=rule('resource_raid_success_floor'):
        loot=take_loot(connection,one,two,survivors,attack['raid_objective'],now,sum(one['config']['units'][u['unit_type']]['loot'] for u in returning))
    building_damage=[]
    with account_scope(two['settlement']['account_id']):
        building_damage=structural.damage_raid(connection,attack,one,two,survivors,returning,result,now,rng,target)
        structural.protect(connection,read_state(connection),now)
        structural_deaths=len({i['citizen_id'] for h in building_damage for i in h['injuries'] if i['hp_after']<=0})
        if structural_deaths:
            delta=max(morale['citizen_death_event_cap'],(d_deaths+structural_deaths)*morale['citizen_death'])-max(morale['citizen_death_event_cap'],d_deaths*morale['citizen_death'])
            for c in read_state(connection)['citizens']:
                if delta:update_morale(connection,c,delta,now,'structural_combat_deaths')
    captures=[];credits_taken=0
    if one.get('expansion'):
        from game.capture import resolve as capture_resolve
        captures=capture_resolve(connection,attack,one,two,result,ids,{c['citizen_id'] for c in defenders},now,rng)
        one=state_at(connection,one['settlement']['settlement_id'],now);two=state_at(connection,two['settlement']['settlement_id'],now)
        if result=='attacker_win' and (survivors or returning):
            from game.vaults import raid as credit_raid
            exposed=sum(h.get('vault_credits',{}).get('exposed',0) for h in missile_report['hits']+building_damage)
            credits_taken=credit_raid(connection,one,two,attack,now,exposed,attack['raid_objective']=='credits')
    drone_returns=drones.finish_return(connection,one,returning,now,attack)
    report={'drone_returns':drone_returns,'allied_ground':allied_losses,'captures':captures,'credits_taken':credits_taken,'missiles':missile_report,'building_damage':building_damage,'attack_id':attack['attack_id'],'attacker':one['settlement']['settlement_name'],'defender':two['settlement']['settlement_name'],'result':result,'resolved_at':now,'objective':attack['raid_objective'],'attack_strength':attack_strength,'defense_strength':defense_strength,'attacker_roll':rolls[0],'defender_roll':rolls[1],'attackers':a_results,'defenders':d_results,'loot':loot,'air_battle':air_report,'offensive_drones':drone_attack_results,'ground_drones':drone_defense_results}
    connection.execute("UPDATE attacks SET status='resolved',resolved_at=?,audit_data=? WHERE attack_id=?",(now,json.dumps(report),attack['attack_id']))
    from game.social import news,notify
    allied_support=allied_losses+air_report.get('allies',[])
    allied_ids={u['settlement_id'] for u in allied_support}|{i['settlement_id'] for i in missile_report['interceptors'] if i.get('settlement_id') not in (one['settlement']['settlement_id'],two['settlement']['settlement_id'])}
    for ally in allies:
        sid=ally['settlement']['settlement_id']
        if sid not in allied_ids:continue
        own_units=[u for u in allied_support if u['settlement_id']==sid]
        own_interceptors=sum(i.get('settlement_id')==sid for i in missile_report['interceptors'])
        text=f'Allied defense in attack #{attack["attack_id"]}: {len(own_units)} drones participated and {own_interceptors} interceptors were used.'
        notify(connection,ally['settlement']['account_id'],ally['season']['season_id'],'allied_defense',text,now,'attack',attack['attack_id'])
        from game.simulation import _event
        _event(connection,ally,'allied_defense_report',now,{'attack_id':attack['attack_id'],'drones':own_units,'interceptors':own_interceptors})
    news(connection,one['season']['season_id'],'raid_resolved',f'Raid resolved: {one["settlement"]["settlement_name"]} attacked {two["settlement"]["settlement_name"]}.',now)
    from game.population import rebalance
    from game.simulation import _event
    for owner in (one,two):
        connection.execute('INSERT INTO battle_reports(attack_id,recipient_settlement_id,created_at,report_data) VALUES (?,?,?,?)',(attack['attack_id'],owner['settlement']['settlement_id'],now,json.dumps(report)))
        _event(connection,owner,'citizen_raid_resolved',now,{'attack_id':attack['attack_id'],'result':result})
        with account_scope(owner['settlement']['account_id']):rebalance(connection,read_state(connection),now)


def resolve_due(connection,state,now):
    if RESOLVING.get() or CURRENT_ACCOUNT.get() is None or not state:return False
    if state['season']['status']=='paused':return False
    token=RESOLVING.set(True);changed=False
    try:
        season=state['season'];limit=min(now,season['ends_at'])
        rows=connection.execute("SELECT * FROM attacks WHERE season_id=? AND status='in_flight' AND resolves_at<=? ORDER BY resolves_at,attack_id",(season['season_id'],limit)).fetchall()
        for attack in rows:resolve(connection,attack,attack['resolves_at']);changed=True
        if now>=season['ends_at']:
            for attack in connection.execute("SELECT * FROM attacks WHERE season_id=? AND status='in_flight'",(season['season_id'],)).fetchall():cancel(connection,attack,season['ends_at'],'Season finished.');changed=True
    finally:RESOLVING.reset(token)
    return changed


def revision(path,state,now):
    sid=state['settlement']['settlement_id']
    with closing(connect_database(path)) as c:
        rows=c.execute('''SELECT attack_id,status FROM attacks WHERE attacker_settlement_id=? OR defender_settlement_id=? ORDER BY attack_id''',(sid,sid)).fetchall()
        treaties=[(row[0],row[1],(row[2] or 0)<=now) for row in c.execute('SELECT treaty_id,status,effective_at FROM treaties WHERE settlement_a_id=? OR settlement_b_id=? ORDER BY treaty_id',(sid,sid))]
    return hashlib.sha256(json.dumps([rows,treaties]).encode()).hexdigest()[:16]


def timers(path,state,now):
    sid=state['settlement']['settlement_id']
    with closing(connect_database(path)) as c:
        from game.admin_controls import timer_now
        return {str(row[0]):max(0,row[1]-timer_now(c,'attack',row[0],now)) for row in c.execute("SELECT attack_id,resolves_at FROM attacks WHERE status='in_flight' AND (attacker_settlement_id=? OR defender_settlement_id=?)",(sid,sid))}


def war_timers(path,state,now):
    sid=state['settlement']['settlement_id']
    with closing(connect_database(path)) as c:
        from game.admin_controls import timer_now
        return {str(row[0]):max(0,row[1]-timer_now(c,'treaty',row[0],now)) for row in c.execute("SELECT treaty_id,effective_at FROM treaties WHERE treaty_type='war' AND status='active' AND (settlement_a_id=? OR settlement_b_id=?)",(sid,sid))}


def panel(path,state,token,now):
    if state['season']['status']=='paused':now=state['season']['paused_at'] or now
    sid=state['settlement']['settlement_id'];hidden=f'<input type="hidden" name="token" value="{escape(token,quote=True)}">'
    with closing(connect_database(path)) as c:
        c.row_factory=sqlite3.Row
        players=c.execute('''SELECT s.settlement_id,s.settlement_name,s.protection_until FROM settlements s JOIN accounts a USING(account_id)
            WHERE season_id=? AND settlement_id!=? AND s.status='active' AND a.is_active=1 ORDER BY s.settlement_name''',(state['season']['season_id'],sid)).fetchall()
        html='<section class="production-panel" id="conflict"><h2>Citizen raids</h2><p>Declare war, wait one hour, then launch a one-hour resource raid. Six citizens must remain at home. Capture and building damage are deferred.</p>'
        if state['season']['config_version'] in ('prototype_v10','prototype_v11','prototype_v12','prototype_v13'):html=html.replace('Citizen raids','Citizen and drone raids')
        html+='<div class="work-cards"><article class="work-card"><h3>1 · Prepare</h3><p>Keep at least six citizens home. Use eligible available citizens, offensive drones or missiles.</p><a href="#military">Equipment production</a> · <a href="#screen-citizens">Citizen roster</a></article><article class="work-card"><h3>2 · Declare war</h3><p>Choose another active settlement below. Wait for the one-hour warning to finish; peace treaties or target protection may block attacks.</p></article><article class="work-card"><h3>3 · Launch</h3><p>Select the same target, choose an objective and select your forces. The raid resolves after its travel time; results appear below.</p></article></div>'
        if not players: html+='<p class="error">No other active settlements are available to attack in this season. Combat needs another enrolled player; creating an account alone does not create a target settlement.</p>'
        html+=f'<p>Attack allowances: {state["settlement"]["attacks_remaining"]} / 3 · reset at midnight UTC. Home citizens: {len(home(state))}.</p>'
        if (state['settlement']['protection_until'] or 0)>now:html+='<p>Your settlement is protected. Launching a raid ends your protection.</p>'
        from game.drones import ready
        ready_drones=ready(state,'offensive_drone')
        from game.structural import ammunition,enabled as structural_enabled
        missile_quantity=sum(i['quantity'] for i in ammunition(state,'missile'))
        if structural_enabled(state):html=html.replace('Capture and building damage are deferred.','Missiles, interception, local turrets and structural damage are enabled. Capture remains deferred.')
        if state.get('expansion'):html=html.replace('Capture remains deferred.','Citizen capture, focused population raids, Credit raids and direct allied hardware defense are enabled.')
        if len(home(state))<=rule('raid_home_population_min') and not ready_drones:html+='<p>Rescue additional survivors through scavenging before you can send raiders.</p>'
        if players:
            options=''.join(f'<option value="{p["settlement_id"]}">{escape(p["settlement_name"])}{" (protected)" if (p["protection_until"] or 0)>now else ""}</option>' for p in players)
            html+='<h3>Declare war</h3>'
            html+=f'<form method="post" action="/conflict" aria-label="Declare war">{hidden}<input type="hidden" name="action" value="declare"><label>Opponent <select name="target_id">{options}</select></label><button>Declare war</button></form>'
            candidates=[citizen for citizen in home(state) if citizen['assignment'] in (('unassigned','administrator') if state['season']['config_version']=='prototype_v13' else ('unassigned',)) and citizen['current_hp']/maximum_hp(state,citizen)>=rule('citizen_low_hp_raid_threshold')/100]
            if (candidates and len(home(state))>rule('raid_home_population_min')) or ready_drones or missile_quantity:
                if len(home(state))<=rule('raid_home_population_min'):candidates=[]
                choices=''.join(f'<label><input type="checkbox" name="citizen_id" value="{citizen["citizen_id"]}">{escape(citizen["name"])} · Level {citizen["level"]} · {citizen["current_hp"]:g} HP</label>' for citizen in candidates)
                choices+=''.join(f'<label><input type="checkbox" name="drone_id" value="{u["unit_id"]}">Offensive Drone #{u["unit_id"]} · {u["current_hp"]:g} HP</label>' for u in ready_drones)
                if missile_quantity:choices+=f'<label>Missiles <input type="number" name="missile_count" min="0" max="{missile_quantity}" value="0"></label>'
                objectives=''.join(f'<option value="{r}">{r.title()}</option>' for r in OBJECTIVES+(('population','credits') if state.get('expansion') else ())+(('infrastructure',) if structural_enabled(state) else ()))
                html+='<h3>Launch a raid</h3><p>Select at least one eligible force. Citizen raids must leave six residents at home; assigned production workers must be released first.</p>'
                html+=f'<form method="post" action="/conflict" aria-label="Launch raid">{hidden}<input type="hidden" name="action" value="launch"><label>Target <select name="target_id">{options}</select></label><label>Objective <select name="objective">{objectives}</select></label><fieldset><legend>Select raiders</legend>{choices}</fieldset><button>Launch raid</button></form>'
            else:
                html+='<p class="error">No eligible attacking force is ready. Free up a healthy citizen while leaving six home, or manufacture an offensive drone / usable missiles.</p><a href="#screen-build">Manage buildings and workers</a>'
        from game.support import guards
        html+=f'<p>Ready offensive drones: {len(ready_drones)}. Ready air-defense drones: {len(ready(state,"air_defense_drone"))}. Ready ground-defense drones: {len(ready(state,"ground_defense_drone"))}. Ready local guards: {len(guards(state))}. Defensive drones deploy automatically when their operational home permits.</p>'
        for treaty in c.execute('''SELECT t.*,a.settlement_name AS a_name,b.settlement_name AS b_name FROM treaties t JOIN settlements a ON a.settlement_id=t.settlement_a_id JOIN settlements b ON b.settlement_id=t.settlement_b_id WHERE t.treaty_type='war' AND t.status='active' AND (settlement_a_id=? OR settlement_b_id=?)''',(sid,sid)):
            html+=f'<p>War: {escape(treaty["a_name"])} / {escape(treaty["b_name"])} · '+(f'warning: <span id="war-timer-{treaty["treaty_id"]}">{max(0,treaty["effective_at"]-now)}</span> seconds remaining.' if now<treaty['effective_at'] else 'attacks unlocked.')+'</p>'
        for attack in c.execute("SELECT * FROM attacks WHERE status='in_flight' AND (attacker_settlement_id=? OR defender_settlement_id=?) ORDER BY resolves_at,attack_id",(sid,sid)):
            incoming=attack['defender_settlement_id']==sid
            label='Incoming hostile attack' if incoming else f'Outgoing raid #{attack["attack_id"]}'
            html+=f'<p>{label}: <span id="raid-timer-{attack["attack_id"]}">{max(0,attack["resolves_at"]-now)}</span> seconds remaining.</p>'
        for row in c.execute('SELECT report_data FROM battle_reports WHERE recipient_settlement_id=? ORDER BY report_id DESC LIMIT 10',(sid,)):
            report=json.loads(row['report_data']);result={'attacker_win':'Raid succeeded','defender_win':'Raid repelled','contested':'Contested — no loot'}[report['result']]
            description=escape(f'Raid #{report["attack_id"]}: {report["attacker"]} → {report["defender"]} · {result}')
            html+=f'<details><summary>{description}</summary><p>Attacking strength: {report["attack_strength"]:.2f}. Defending strength: {report["defense_strength"]:.2f}.</p>'
            for side in ('attackers','defenders'):
                html+='<p>'+side.title()+': '+('; '.join(f'{escape(c["name"])}: {c["hp_before"]:g} → {c["hp_after"]:g} HP ({c["outcome"]})' for c in report[side]) or 'none')+'.</p>'
            air=report.get('air_battle',{})
            if air.get('result'):html+=f'<p>Air battle: {escape(air["result"])} · {air["attack_strength"]:.2f} attacking / {air["defense_strength"]:.2f} defending.</p>'
            for label,units in [('Air attackers',air.get('attackers',[])),('Air defenders',air.get('defenders',[])),('Raid drones',report.get('offensive_drones',[])),('Ground defense',report.get('ground_drones',[]))]:
                if units:html+='<p>'+label+': '+'; '.join(f'{escape(u["type"].replace("_"," "))} #{u["unit_id"]}: {u["hp_before"]:g} → {u["hp_after"]:g} HP ({u["outcome"]})' for u in units)+'.</p>'
            for unit in report.get('drone_returns',[]):
                disposition='destroyed on return: no compatible free storage slot' if unit['outcome']=='destroyed_no_home' else f'returned to home #{unit["home_building_id"]}'
                html+=f'<p>Drone #{unit["unit_id"]}: {disposition}. Earned rewards are included below.</p>'
            for key,label in [('taken','Stolen'),('deposited','Delivered'),('lost','Lost to storage overflow')]:
                html+='<p>'+label+': '+(', '.join(f'{value:.2f} {resource.title()}' for resource,value in report['loot'][key].items() if value>1e-8) or 'none')+'.</p>'
            missiles=report.get('missiles',{})
            if missiles.get('launched'):html+=f'<p>Missiles launched: {missiles["launched"]}; intercepted: {missiles["intercepted"]}.</p>'
            for hit in missiles.get('hits',[])+report.get('building_damage',[]):
                html+=f'<p>{escape(hit["type"].replace("_"," "))} #{hit["building_id"]}: {hit["hp_before"]:.2f} → {hit["hp_after"]:.2f} HP'+(' · destroyed' if hit['destroyed'] else '')+'.</p>'
                for injury in hit['injuries']:
                    html+=f'<p>Occupant #{injury["citizen_id"]}: {injury["hp_before"]:.2f} to {injury["hp_after"]:.2f} HP.</p>'
            if report.get('credits_taken'):html+=f'<p>Credits captured: {report["credits_taken"]}.</p>'
            for capture in report.get('captures',[]):html+=f'<p>Captured citizen: {escape(capture["name"])}.</p>'
            html+='</details>'
        for row in c.execute("SELECT attack_id,cancel_reason FROM attacks WHERE status='cancelled' AND (attacker_settlement_id=? OR defender_settlement_id=?) ORDER BY attack_id DESC LIMIT 10",(sid,sid)):
            html+=f'<p>Raid #{row["attack_id"]} recalled: {escape(row["cancel_reason"])} Allowance refunded.</p>'
        return html+'</section>'

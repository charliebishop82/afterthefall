"""Citizen exposure, housing hardship, employment, births and departures."""
import copy,json,math,random
from html import escape
from game.settlement import read_state,account_scope


def enabled(state):return 'consequences' in state['config']


def record(connection,state,now,clock):
    from game.simulation import _event
    _event(connection,state,'citizen_consequences_clock',now,clock)


def enable(connection,state,now):
    if enabled(state):return
    from game.structural import enable as structural
    structural(connection,state,now)
    connection.execute("UPDATE seasons SET config_version='prototype_v13' WHERE season_id=?",(state['season']['season_id'],))
    for row in connection.execute('SELECT settlement_id FROM settlements WHERE season_id=?',(state['season']['season_id'],)).fetchall():
        previous=connection.execute("SELECT 1 FROM game_events WHERE settlement_id=? AND event_type='citizen_consequences_clock'",(row[0],)).fetchone()
        if not previous:
            from game.simulation import _event
            owner={**state,'settlement':{**state['settlement'],'settlement_id':row[0]}}
            _event(connection,owner,'citizen_consequences_clock',now,{'enabled_at':now,'exposed':{},'deliberate':[],'day':now//86400,'seed':state['season']['map_seed']})
    from game.simulation import _event
    _event(connection,state,'prototype_config_enabled',now,{'from':state['season']['config_version'],'to':'prototype_v13'})


def deliberate(state,c):
    return enabled(state) and c['assignment_id'] in state['consequences_clock']['deliberate']


def authorize(connection,state,aid,now):
    clock=copy.deepcopy(state['consequences_clock']);clock['deliberate'].append(aid)
    c=connection.execute('SELECT citizen_id FROM citizen_assignments WHERE assignment_id=?',(aid,)).fetchone()
    clock['exposed'][str(c[0])]=aid
    record(connection,state,now,clock)


def unsafe(state,c):
    from game.buildings import coverage
    if c.get('away') or c['assignment']=='unassigned':return False
    if c['building_id']:
        b=next(b for b in state['buildings'] if b['building_id']==c['building_id'])
        if b['building_type']=='town_hall':return False
        geometric=coverage(state,b)<state['config']['construction']['coverage_fraction']
        if c['assignment'] in ('production','defender'):
            from game.economy import utilities
            reason=utilities(state)['buildings'][b['building_id']]['reason']
            return geometric or reason=='Not enough oxygen capacity'
        return geometric
    if c['assignment']=='scavenging' and c['job_id']:
        from game.scavenging import safe_coverage
        j=next(j for j in state['jobs'] if j['job_id']==c['job_id']);d=next(d for d in state['derelicts'] if d['settlement_derelict_id']==j['target_derelict_id'])
        return safe_coverage(state,d)<state['config']['construction']['coverage_fraction']
    return False


def release(connection,c,now,reason):
    connection.execute('UPDATE citizen_assignments SET ended_at=?,end_reason=? WHERE citizen_id=? AND ended_at IS NULL',(now,reason,c['citizen_id']))
    connection.execute('UPDATE citizens SET unemployed_since=? WHERE citizen_id=?',(now,c['citizen_id']))


def synchronize(connection,state,now):
    from game.structural import rearm
    rearm(connection,state,now)
    if not enabled(state):return False
    if now<state['consequences_clock']['enabled_at']:return False
    clock=copy.deepcopy(state['consequences_clock']);changed=False;exposed={}
    for c in state['citizens']:
        if unsafe(state,c):
            if deliberate(state,c):
                if c['current_hp']<=max_hp(state,c)*state['config']['consequences']['evacuation_fraction']:
                    release(connection,c,now,'emergency_oxygen_evacuation');changed=True
                else:exposed[str(c['citizen_id'])]=c['assignment_id']
            else:release(connection,c,now,'oxygen_outage_evacuation');changed=True
    if exposed!=clock['exposed']:clock['exposed']=exposed;changed=True
    active={c['assignment_id'] for c in state['citizens'] if str(c['citizen_id']) in exposed}
    kept=[a for a in clock['deliberate'] if a in active]
    if kept!=clock['deliberate']:clock['deliberate']=kept;changed=True
    if changed:record(connection,state,now,clock)
    from game.structural import rearm
    rearm(connection,state,now)
    if not any(c['assignment']=='administrator' for c in state['citizens']):
        before=connection.total_changes
        replace_admin(connection,read_state(connection),now)
        changed=changed or connection.total_changes!=before
    return changed


def max_hp(state,c):return state['config']['citizen_hp']+(c['level']-1)*state['config']['simulation']['hp_per_level']


def die(connection,state,c,now,cause,related=None):
    connection.execute("UPDATE citizens SET status='dead',current_hp=0,died_at=?,death_cause=?,death_related_id=? WHERE citizen_id=? AND status='alive'",(now,cause,related,c['citizen_id']))
    release(connection,c,now,cause)
    connection.execute('UPDATE citizen_settlement_history SET left_at=?,departure_reason=? WHERE citizen_id=? AND left_at IS NULL',(now,cause,c['citizen_id']))
    from game.simulation import _event
    _event(connection,state,'citizen_died',now,{'citizen_id':c['citizen_id'],'cause':cause,'related_id':related})


def replace_admin(connection,state,now):
    if any(c['assignment']=='administrator' for c in state['citizens']):return
    free=[c for c in state['citizens'] if c['assignment']=='unassigned' and not c.get('away') and c['current_hp']>0]
    if free:
        c=min(free,key=lambda c:(-c['level'],-c['xp'],c['joined_at'],c['citizen_id']))
        connection.execute("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,building_id,assigned_at) VALUES (?,?,'administrator',?,?)",(c['citizen_id'],state['settlement']['settlement_id'],state['buildings'][0]['building_id'],now))
        connection.execute('UPDATE citizens SET unemployed_since=NULL WHERE citizen_id=?',(c['citizen_id'],))


def next_boundary(state):
    if not enabled(state):return None
    now=state['settlement']['simulation_processed_at'];times=[(now//86400+1)*86400]
    r=state['config']['consequences'];clock=state['consequences_clock']
    if now<clock['enabled_at']:return clock['enabled_at']
    if clock['exposed'] or any(not c.get('away') and (c['homeless_since'] is not None or c['assignment']=='unassigned') for c in state['citizens']):times.append(now+60)
    for c in state['citizens']:
        if str(c['citizen_id']) in clock['exposed']:
            loss=max_hp(state,c)/(60*(r['oxygen_minutes']+(c['level']-1)*r['oxygen_level_minutes']))
            times.append(now+max(1,math.ceil((c['current_hp']-max_hp(state,c)*r['evacuation_fraction'])/loss)))
        for key,hours in [('homeless_since',r['homeless_grace_hours']),('unemployed_since',r['unemployment_grace_hours'])]:
            since=c.get(key)
            if since is not None:
                boundary=max(clock['enabled_at'],since)+hours*3600
                if boundary>now:times.append(boundary)
    return min(times)


def accrue(connection,state,seconds,now):
    if not enabled(state) or seconds<=0:return
    from game.combat import update_morale,settings
    r=state['config']['consequences'];clock=state['consequences_clock'];start=now-seconds;deaths=0
    start=max(start,clock['enabled_at']);seconds=max(0,now-start)
    if not seconds:return
    for c in state['citizens']:
        if c.get('away'):continue
        damage=0
        if str(c['citizen_id']) in clock['exposed']:damage+=max_hp(state,c)*seconds/(60*(r['oxygen_minutes']+(c['level']-1)*r['oxygen_level_minutes']))
        if c['homeless_since'] is not None:
            after=max(start,max(clock['enabled_at'],c['homeless_since'])+r['homeless_grace_hours']*3600)
            damage+=max(0,now-after)*r['homeless_hp_hour']/3600
        if damage:
            row=connection.execute('SELECT current_hp,status FROM citizens WHERE citizen_id=?',(c['citizen_id'],)).fetchone()
            if row['status']=='alive':
                hp=max(0,row['current_hp']-damage)
                connection.execute('UPDATE citizens SET current_hp=? WHERE citizen_id=?',(hp,c['citizen_id']))
                if hp<=0:die(connection,state,c,now,'unmet_citizen_needs');deaths+=1
        since=c.get('unemployed_since')
        if c['assignment']=='unassigned' and since is not None:
            after=max(start,max(clock['enabled_at'],since)+r['unemployment_grace_hours']*3600)
            delta=-max(0,now-after)*r['unemployment_morale_day']/86400
            if delta:
                current=dict(c);current['morale']=connection.execute('SELECT morale FROM citizens WHERE citizen_id=?',(c['citizen_id'],)).fetchone()[0]
                update_morale(connection,current,delta,now,'unemployment')
    if deaths:
        current=read_state(connection);morale=settings()['Morale'];delta=max(morale['citizen_death_event_cap'],deaths*morale['citizen_death'])
        for c in current['citizens']:update_morale(connection,c,delta,now,'citizen_needs_death')
        replace_admin(connection,read_state(connection),now)


def birth_chance(state):
    if not enabled(state):return 0
    from game.economy import rates,available_food
    from game.trading import available
    r=state['config']['consequences'];home=[c for c in state['citizens'] if not c.get('away')];capacity=state['recovery_housing']['capacity']
    if not home or not {'male','female'}.issubset({c['sex'] for c in home}) or len(state['citizens'])>=capacity:return 0
    if sum(c['effective_morale'] for c in home)/len(home)<r['birth_min_morale']:return 0
    flow=rates(state)
    for resource in ('food','water'):
        stock=available_food(state) if resource=='food' else available(state,resource)
        newborn=state['config']['simulation'][f'{resource}_per_citizen_per_hour']
        if state.get('needs_clock') is not None:
            newborn=state['config']['needs']['rations'][resource][state['policies'][resource+'_ration']]['consumption']
        consumption=flow[resource]['consumption']+newborn
        if stock+24*flow[resource]['production']+1e-9<24*consumption:return 0
    occupancy=len(state['citizens'])/capacity
    return r['birth_chance']*min(1,max(0,(1-occupancy)/(1-r['birth_slowdown'])))


def depart(connection,state,c,now,reason):
    release(connection,c,now,reason)
    connection.execute('UPDATE citizens SET status=? WHERE citizen_id=?',(reason,c['citizen_id']))
    connection.execute('UPDATE citizen_settlement_history SET left_at=?,departure_reason=? WHERE citizen_id=? AND left_at IS NULL',(now,reason,c['citizen_id']))
    from game.simulation import _event
    _event(connection,state,'citizen_departed',now,{'citizen_id':c['citizen_id'],'reason':reason})


def daily(connection,state,now):
    if not enabled(state):return False
    clock=copy.deepcopy(state['consequences_clock']);day=now//86400
    if now<clock['enabled_at'] or day<=clock['day'] or now>=state['season']['ends_at']:return False
    from game.population import generated_name,rebalance
    from game.simulation import _event
    r=state['config']['consequences'];rng=random.Random(f'{clock["seed"]}:{state["settlement"]["settlement_id"]}:{day}:citizens')
    home=[c for c in state['citizens'] if not c.get('away')]
    remaining=len(home);departures=[];checks=[]
    for c in home:
        if state.get('expansion') and (not c['integrated'] or connection.execute("SELECT 1 FROM game_events WHERE settlement_id=? AND event_type='captured_citizen_integrated' AND occurred_at=? AND json_extract(event_data,'$.citizen_id')=?",(state['settlement']['settlement_id'],now,c['citizen_id'])).fetchone()):continue
        chance=r['desertion_max_chance']*max(0,1-c['effective_morale']/r['desertion_threshold']);roll=rng.random()
        checks.append({'citizen_id':c['citizen_id'],'morale':c['effective_morale'],
                       'chance':chance,'roll':roll,'home_population':remaining,
                       'floor_blocked':remaining<=r['population_floor'],
                       'deserted':remaining>r['population_floor'] and roll<chance})
        if remaining>r['population_floor'] and roll<chance:
            depart(connection,state,c,now,'deserted');remaining-=1;departures.append(c['citizen_id'])
    replace_admin(connection,read_state(connection),now)
    rebalance(connection,read_state(connection),now)
    current=read_state(connection);probability=birth_chance(current);roll=rng.random();born=None
    from game.economy import rates,available_food
    from game.trading import available
    flow=rates(current)
    birth_inputs={'population':len(current['citizens']),'housing_capacity':current['recovery_housing']['capacity'],
                  'home_citizens':[{'citizen_id':c['citizen_id'],'sex':c['sex'],'morale':c['effective_morale']}
                                   for c in current['citizens'] if not c.get('away')],
                  'food_available':available_food(current),'water_available':available(current,'water'),
                  'supply_rates':{resource:{key:flow[resource][key] for key in ('production','consumption')}
                                  for resource in ('food','water')}}
    if roll<probability:
        sid=state['settlement']['settlement_id'];name=generated_name(connection,sid,rng);sex=rng.choice(('male','female'))
        born=connection.execute("INSERT INTO citizens(settlement_id,original_settlement_id,name,sex,level,current_hp,morale,status,unemployed_since,created_at) VALUES (?,?,?,?,1,?,?,'alive',?,?)",(sid,sid,name,sex,state['config']['citizen_hp'],state['config']['citizen_morale'],now,now)).lastrowid
        connection.execute("INSERT INTO citizen_settlement_history(citizen_id,settlement_id,joined_at,arrival_reason) VALUES (?,?,?,'birth')",(born,sid,now))
        connection.execute('INSERT INTO citizen_level_history(citizen_id,level,xp_total,reached_at) VALUES (?,1,0,?)',(born,now))
    floor_arrivals=[]
    count=connection.execute("SELECT count(*) FROM citizens WHERE settlement_id=? AND status='alive'",(state['settlement']['settlement_id'],)).fetchone()[0]
    for ordinal in range(max(0,r['population_floor']-count)):
        sid=state['settlement']['settlement_id'];name=generated_name(connection,sid,rng);sex=rng.choice(('male','female'))
        cid=connection.execute("INSERT INTO citizens(settlement_id,original_settlement_id,name,sex,level,current_hp,morale,status,unemployed_since,created_at) VALUES (?,?,?,?,1,?,?,'alive',?,?)",(sid,sid,name,sex,state['config']['citizen_hp'],state['config']['citizen_morale'],now,now)).lastrowid
        connection.execute("INSERT INTO citizen_settlement_history(citizen_id,settlement_id,joined_at,arrival_reason) VALUES (?,?,?,'midnight_population_floor')",(cid,sid,now))
        connection.execute('INSERT INTO citizen_level_history(citizen_id,level,xp_total,reached_at) VALUES (?,1,0,?)',(cid,now))
        floor_arrivals.append(cid)
    replace_admin(connection,read_state(connection),now)
    clock['day']=day;record(connection,state,now,clock)
    _event(connection,state,'citizen_daily_rollover',now,{'day':day,'deserted':departures,'desertion_checks':checks,'birth_chance':probability,'birth_roll':roll,'birth_inputs':birth_inputs,'birth_citizen_id':born,'floor_arrivals':floor_arrivals})
    rebalance(connection,read_state(connection),now)
    return True


def command(connection,state,cid,now):
    if not enabled(state):raise ValueError('Enable citizen consequences first.')
    c=next((c for c in state['citizens'] if c['citizen_id']==cid and not c.get('away')),None)
    if not c:raise ValueError('Choose your own citizen at home.')
    if sum(not c.get('away') for c in state['citizens'])<=state['config']['consequences']['population_floor']:raise ValueError('At least six citizens must remain physically at home.')
    depart(connection,state,c,now,'expelled');replace_admin(connection,read_state(connection),now)
    from game.combat import update_morale
    for survivor in read_state(connection)['citizens']:update_morale(connection,survivor,state['config']['consequences']['expulsion_morale'],now,'citizen_expulsion')
    from game.population import rebalance
    rebalance(connection,read_state(connection),now)


def shift_clock(connection,state,seconds,now):
    if not enabled(state) or not seconds:return
    clock=copy.deepcopy(state['consequences_clock']);clock['enabled_at']+=seconds;clock['day']=now//86400
    record(connection,state,now,clock)


def panel(state,token):
    from game.building_views import form
    if not enabled(state):return '<section class="production-panel"><h2>Citizen consequences</h2><p>Enable Oxygen evacuation, homelessness health loss, unemployment morale, births, desertion and expulsion from this point forward.</p>'+form(token,'enable_consequences','<button>Enable citizen consequences</button>')+'</section>'
    result='<section class="production-panel"><h2>Citizen wellbeing</h2><p>Unexpected Oxygen loss evacuates workers. Deliberate exposed work rapidly injures citizens; they evacuate at 25% HP. Homelessness damages health after 12 hours. Unemployment lowers morale by 1 per day after 12 hours. Births and low-morale desertion are checked at midnight UTC.</p>'
    result+=f'<p>Current daily birth chance: {birth_chance(state)*100:.2f}%. Six citizens must remain at home after expulsion or ordinary desertion.</p>'
    for c in state['citizens']:
        if c.get('away'):continue
        note=' · exposed to Oxygen loss' if str(c['citizen_id']) in state['consequences_clock']['exposed'] else ''
        result+=f'<p>{escape(c["name"])}: {c["current_hp"]:.2f} HP · {c["effective_morale"]:.2f} morale{note}</p>'
    if sum(not c.get('away') for c in state['citizens'])>6:
        choices=''.join(f'<option value="{c["citizen_id"]}">{escape(c["name"])}</option>' for c in state['citizens'] if not c.get('away'))
        result+=form(token,'expel',f'<label>Citizen <select name="citizen_id">{choices}</select></label><p>Expelling a citizen costs each survivor 3 morale.</p><button>Expel citizen</button>')
    return result+'</section>'

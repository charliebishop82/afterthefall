"""One private survivor opportunity per ruin, and automatic safe housing."""
import json
import math
import random

from game.settlement import load_config, read_state


def unique_name(connection, settlement_id, proposed):
    """Choose a globally unused identity before arrival; preserve existing names."""
    used = {r[0] for r in connection.execute('SELECT name FROM citizens')}
    if proposed not in used:
        return proposed
    for first in ('Leah','Owen','Iris','Theo','Ruth','Kai','June','Finn'):
        for surname in ('Ash','Brooks','Carter','Frost','Hale','Lake','Quinn','Wells'):
            candidate = first + ' ' + surname
            if candidate not in used:
                return candidate
    ordinal = 2
    while f'{proposed} {ordinal}' in used:
        ordinal += 1
    return f'{proposed} {ordinal}'


def generated_name(connection, settlement_id, rng):
    proposed = rng.choice(('Leah','Owen','Iris','Theo','Ruth','Kai','June','Finn')) + ' ' + rng.choice(('Ash','Brooks','Carter','Frost','Hale','Lake','Quinn','Wells'))
    return unique_name(connection, settlement_id, proposed)


def enabled(state):
    return state['season']['config_version'] in ('prototype_v5','prototype_v6','prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13')


def enable(connection, state, now):
    if enabled(state):
        return
    from game.scavenging import enable as enable_production
    enable_production(connection, state, now)
    state = read_state(connection)
    connection.execute("UPDATE seasons SET config_version='prototype_v5' WHERE season_id=?",
                       (state['season']['season_id'],))
    for d in state['derelicts']:
        if d['status'] == 'cleared':
            continue  # Never retroactively reward already cleared ruins.
        loot = json.loads(d['random_result'])
        rng = random.Random(d['random_nonce'] + ':survivor-v1')
        job = next((j for j in state['jobs'] if j['target_derelict_id'] == d['settlement_derelict_id']), None)
        fraction = job['work_completed'] / job['work_required'] if job else 0
        loot['_survivor'] = {'at_fraction':fraction + (1-fraction)*rng.uniform(.15,.85),
            'roll_pct':rng.random()*100, 'resolved':False,
            'name':rng.choice(('Leah','Owen','Iris','Theo','Ruth','Kai','June','Finn')) + ' ' +
                   rng.choice(('Ash','Brooks','Carter','Frost','Hale','Lake','Quinn','Wells')),
            'sex':rng.choice(('female','male'))}
        connection.execute('UPDATE settlement_derelicts SET random_result=? WHERE settlement_derelict_id=?',
                           (json.dumps(loot),d['settlement_derelict_id']))
    from game.simulation import _event
    _event(connection,state,'prototype_config_enabled',now,{'from':state['season']['config_version'],'to':'prototype_v5'})
    rebalance(connection,read_state(connection),now)


def chance(state, derelict):
    base = state['config']['derelicts'][derelict['derelict_type']]['survivor_chance_pct']
    decay = state['config']['population']['chance_decay_per_citizen']
    return max(0,base-max(0,len(state['citizens'])-6)*decay)


def next_discovery(state, job, speed):
    if not enabled(state) or job['job_type'] != 'scavenging' or speed <= 0:
        return None
    d = next(d for d in state['derelicts'] if d['settlement_derelict_id'] == job['target_derelict_id'])
    event = json.loads(d['random_result']).get('_survivor')
    if not event or event['resolved']:
        return None
    return max(1,math.ceil((event['at_fraction']*job['work_required']-job['work_completed'])/speed-1e-9))


def discover(connection, state, derelict, fraction, now):
    if not enabled(state):
        return
    loot = json.loads(derelict['random_result'])
    event = loot.get('_survivor')
    if not event or event['resolved'] or fraction+1e-9 < event['at_fraction']:
        return
    # Resolve once in the same transaction as loot and elapsed-time progress.
    current = read_state(connection)
    probability = chance(current,derelict)
    event['resolved'] = True
    event['chance_pct'] = probability
    if event['roll_pct'] < probability:
        sid = state['settlement']['settlement_id']
        event['name'] = unique_name(connection, sid, event['name'])
        p = state['config']['population']
        citizen_id = connection.execute('''INSERT INTO citizens
            (settlement_id,original_settlement_id,name,sex,level,current_hp,morale,status,unemployed_since,created_at)
            VALUES (?,?,?,?,?,?,?,'alive',?,?)''',
            (sid,sid,event['name'],event['sex'],p['survivor_level'],
             state['config']['citizen_hp']*p['survivor_hp_fraction'],p['survivor_morale'],now,now)).lastrowid
        connection.execute('''INSERT INTO citizen_settlement_history
            (citizen_id,settlement_id,joined_at,arrival_reason) VALUES (?,?,?,'scavenged_survivor')''',
            (citizen_id,sid,now))
        connection.execute('INSERT INTO citizen_level_history(citizen_id,level,xp_total,reached_at) VALUES (?,1,0,?)',
                           (citizen_id,now))
        event['citizen_id'] = citizen_id
        from game.simulation import _event
        _event(connection,state,'prototype_survivor_arrived',now,
               {'citizen_id':citizen_id,'derelict_id':derelict['settlement_derelict_id']})
    connection.execute('UPDATE settlement_derelicts SET random_result=? WHERE settlement_derelict_id=?',
                       (json.dumps(loot),derelict['settlement_derelict_id']))


def housing(state, utility=None):
    from game.buildings import spec, rules
    from game.economy import utilities, zone_fraction, condition
    if utility is None and 'recovery_housing' in state:
        return state['recovery_housing']
    utility = utilities(state) if utility is None else utility
    homes = []
    for b in state['buildings']:
        s = spec(state,b)
        if not s.get('housing') or b['status'] not in ('active','upgrading'):
            continue
        safe = zone_fraction(state,b,utility['zones']['oxygen']) >= rules(state)['construction']['coverage_fraction']
        if b['building_type'] != 'town_hall':
            safe = safe and not utility['buildings'][b['building_id']]['reason']
        capacity = math.floor(s['housing']*condition(state,b)+1e-9) if safe else 0
        quality=s.get('morale_bonus',0)
        if state['season']['config_version'] in ('prototype_v6','prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13') and b['building_type'] in ('house','apartment_block'):
            if zone_fraction(state,b,utility['zones']['electricity']) >= rules(state)['construction']['coverage_fraction']:
                quality+=state['config']['recovery']['powered_comfort']
        homes.append({'building_id':b['building_id'],'name':rules(state)['buildings'][b['building_type']]['name'],
                      'capacity':capacity,'quality':quality})
    slots = [h for h in sorted(homes,key=lambda h:(-h['quality'],h['building_id'])) for _ in range(h['capacity'])]
    citizens = sorted(state['citizens'],key=lambda c:(-c['level'],-c['xp'],c['joined_at'],c['citizen_id']))
    assignments = {c['citizen_id']:slots[i] if i<len(slots) else None for i,c in enumerate(citizens)}
    return {'capacity':sum(h['capacity'] for h in homes),'homes':homes,'assignments':assignments,
            'homeless':sum(h is None for h in assignments.values())}


def rebalance(connection, state, now):
    if not enabled(state):
        return
    allocation = housing(state)['assignments']
    for c in state['citizens']:
        if allocation[c['citizen_id']] is None and c['homeless_since'] is None:
            after = max(0,c['morale']+state['config']['population']['homeless_penalty'])
            connection.execute('UPDATE citizens SET homeless_since=?,morale=? WHERE citizen_id=?',
                               (now,after,c['citizen_id']))
            connection.execute('''INSERT INTO citizen_morale_events
                (citizen_id,morale_before,morale_after,reason,occurred_at) VALUES (?,?,?,'became_homeless',?)''',
                (c['citizen_id'],c['morale'],after,now))
        elif allocation[c['citizen_id']] is not None and c['homeless_since'] is not None:
            connection.execute('UPDATE citizens SET homeless_since=NULL WHERE citizen_id=?',(c['citizen_id'],))

"""Building geometry, utilities, and transactional construction commands.

Work is measured in equivalent seconds from the workbook's one-worker time.
No schema changes or background timers are needed.
"""

from contextlib import closing
import json
import math
import sqlite3
import time

from database.create_database import connect_database
from game.settlement import load_config, read_state


def rules(state):
    return state['config'] if 'buildings' in state['config'] else load_config('prototype_v3')


def expanded(state):
    return state['season']['config_version'] in ('prototype_v4','prototype_v5','prototype_v6','prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13')


def spec(state, building, level=None):
    return rules(state)['buildings'][building['building_type']]['levels'][(level or building['level']) - 1]


def minimum_hp(state, building):
    """The Town Hall survives damage at one quarter of its level maximum."""
    return spec(state, building)['hp'] * .25 if building['building_type'] == 'town_hall' else 0


def footprint(state, building):
    width, height = rules(state)['buildings'][building['building_type']]['footprint']
    return (height, width) if building['rotation'] in (90, 270) else (width, height)


def productivity(state, citizen):
    if citizen.get('away'):return 0
    sim = rules(state)['simulation']
    max_hp = state['config']['citizen_hp'] + (citizen['level'] - 1) * sim['hp_per_level']
    health = max(0, min(1, citizen['current_hp'] / max_hp))
    morale = next(factor for upper, factor in sim['morale_bands'] if citizen.get('effective_morale',citizen['morale']) < upper)
    return health * morale * (1 + (citizen['level'] - 1) * sim['productivity_per_level'])


def coverage(state, building):
    """Fraction of footprint tile centers within the Town Hall's rounded zone."""
    if expanded(state):
        from game.economy import utilities, zone_fraction
        return zone_fraction(state,building,utilities(state)['zones']['oxygen'])
    hall = state['buildings'][0]
    if hall['status'] not in ('active', 'upgrading'):
        return 0
    if hall['current_hp'] / spec(state, hall)['hp'] <= rules(state)['construction']['shutdown_condition']:
        return 0
    radius = spec(state, hall)['radius']
    hx, hy = hall['origin_x'], hall['origin_y']
    hw, hh = footprint(state, hall)
    width, height = footprint(state, building)
    covered = 0
    for x in range(building['origin_x'], building['origin_x'] + width):
        for y in range(building['origin_y'], building['origin_y'] + height):
            dx = max(hx - (x + .5), 0, (x + .5) - (hx + hw))
            dy = max(hy - (y + .5), 0, (y + .5) - (hy + hh))
            covered += dx * dx + dy * dy <= radius * radius
    return covered / (width * height)


def operating_status(state):
    """Allocate the Town Hall's finite utilities to oldest eligible Food buildings."""
    if expanded(state):
        from game.economy import production_status
        return production_status(state)
    hall = state['buildings'][0]
    hall_spec = spec(state, hall)
    condition = min(1, hall['current_hp'] / hall_spec['hp'])
    available = {k: hall_spec[k + '_output'] * condition for k in ('oxygen', 'electricity')}
    if condition <= rules(state)['construction']['shutdown_condition']:
        available = dict.fromkeys(available, 0)
    result = {}
    for b in sorted(state['buildings'][1:], key=lambda b: (b['completed_at'] or b['created_at'], b['building_id'])):
        s = spec(state, b)
        workers = [c for c in state['citizens'] if c['building_id'] == b['building_id'] and c['assignment'] == 'production']
        reason = ''
        if b['status'] != 'active':
            reason = 'Construction in progress' if b['status'] == 'construction' else 'Upgrade in progress'
        elif b['current_hp'] / s['hp'] <= rules(state)['construction']['shutdown_condition']:
            reason = 'Too damaged to operate'
        elif coverage(state, b) < rules(state)['construction']['coverage_fraction']:
            reason = 'Outside Town Hall utility coverage'
        elif not any(productivity(state, c) > 0 for c in workers):
            reason = 'Assign a Food worker'
        else:
            for utility in available:
                if s[utility + '_demand'] > available[utility] + 1e-9:
                    reason = 'Not enough ' + utility + ' capacity'
                    break
        if not reason:
            for utility in available:
                available[utility] -= s[utility + '_demand']
        result[b['building_id']] = {
            'reason': reason, 'workers': len(workers),
            'output': 0 if reason else s['food'] * min(1, b['current_hp'] / s['hp']) * sum(productivity(state, c) for c in workers),
        }
    return result


def job_speed(state, job):
    if job['job_type']=='building_salvage':
        from game.ruins import speed
        return speed(state,job)
    if job['job_type']=='drone_repair':
        from game.maintenance import speed
        return speed(state,job)
    if job['job_type']=='manufacturing':
        from game.manufacturing import speed
        return speed(state,job)
    if job['job_type']=='repair':
        from game.repairs import speed
        return speed(state,job)
    if job['job_type']=='scavenging':
        from game.scavenging import speed
        return speed(state,job)
    b = next(b for b in state['buildings'] if b['building_id'] == job['target_building_id'])
    if b['status'] not in ('construction', 'upgrading') or job['status'] not in ('active', 'paused'):
        return 0
    from game.consequences import deliberate
    if b['building_type'] != 'town_hall' and coverage(state, b) < rules(state)['construction']['coverage_fraction'] and not all(deliberate(state,c) for c in state['citizens'] if c['job_id']==job['job_id']):
        return 0
    workers = [c for c in state['citizens'] if c['job_id'] == job['job_id'] and c['assignment'] == 'construction']
    if not workers:
        return 0
    from game.support import best
    return sum(productivity(state, c) for c in workers) / len(workers) ** (1 - rules(state)['construction']['worker_exponent']) * (1+best(state,'construction_bonus')/100)


def next_completion(state):
    seconds = [max(1, math.ceil((j['work_required'] - j['work_completed']) / job_speed(state, j) - 1e-9))
               for j in state['jobs'] if job_speed(state, j) > 0]
    from game.population import next_discovery
    seconds += [boundary for j in state['jobs']
                if (boundary := next_discovery(state,j,job_speed(state,j))) is not None]
    return min(seconds) if seconds else None


def resource_rates(state):
    if expanded(state):
        from game.economy import rates
        return rates(state)
    hall = state['buildings'][0]
    hs = spec(state, hall)
    condition = min(1, hall['current_hp'] / hs['hp'])
    admin = next((c for c in state['citizens'] if c['assignment'] == 'administrator'), None)
    efficiency = productivity(state, admin) if admin and hall['status'] in ('active', 'upgrading') else 0
    if hall['status'] == 'upgrading':
        efficiency *= rules(state)['construction']['town_hall_upgrade_productivity']
    food_output = sum(b['output'] for b in operating_status(state).values())
    # Completed storage remains available during upgrades; construction adds none.
    food_storage = sum(spec(state, b)['food_storage'] * min(1, b['current_hp'] / spec(state, b)['hp'])
                       for b in state['buildings'][1:] if b['status'] in ('active', 'upgrading'))
    result = {}
    for resource in ('food', 'water'):
        production = hs[resource] * efficiency * condition + (food_output if resource == 'food' else 0)
        consumption = sum(not c.get('away') for c in state['citizens']) * rules(state)['simulation'][resource + '_per_citizen_per_hour']
        net = production - consumption
        capacity = hs[resource + '_storage'] * condition + (food_storage if resource == 'food' else 0)
        result[resource] = dict(production=production, consumption=consumption, net=net, capacity=capacity,
                               hours_to_empty=state['resources'][resource] / -net if net < 0 else None)
    return result


def progress_jobs(connection, state, seconds, now):
    for job in state['jobs']:
        if job['status'] not in ('active', 'paused'):
            continue
        if job['job_type']=='building_salvage':
            from game.ruins import progress
            progress(connection,state,job,seconds,now)
            continue
        if job['job_type']=='drone_repair':
            from game.maintenance import progress
            progress(connection,state,job,seconds,now)
            continue
        if job['job_type']=='manufacturing':
            from game.manufacturing import progress
            progress(connection,state,job,seconds,now)
            continue
        if job['job_type']=='repair':
            from game.repairs import progress
            progress(connection,state,job,seconds,now)
            continue
        if job['job_type']=='scavenging':
            from game.scavenging import progress
            progress(connection,state,job,seconds,now)
            continue
        speed = job_speed(state, job)
        done = min(job['work_required'], job['work_completed'] + seconds * speed)
        if job['work_required'] - done < 1e-7:
            done = job['work_required']
        complete = done == job['work_required']
        connection.execute('''UPDATE settlement_jobs SET work_completed=?,last_processed_at=?,
            status=?,pause_reason=?,completed_at=?,started_at=COALESCE(started_at,?) WHERE job_id=?''',
            (done, now, 'completed' if complete else 'active' if speed else 'paused',
             None if speed else 'No effective builders or unsafe Oxygen coverage', now if complete else None,
             state['settlement']['simulation_processed_at'] if speed else None, job['job_id']))
        b = next(b for b in state['buildings'] if b['building_id'] == job['target_building_id'])
        target_level = b['level'] + (job['job_type'] == 'upgrade')
        if complete:
            old_max = spec(state, b)['hp']
            new_max = spec(state, b, target_level)['hp']
            hp = max(0,new_max-json.loads(job['inputs_spent']).get('_damage',0)) if job['job_type'] == 'construction' else new_max * min(1, b['current_hp'] / old_max)
            connection.execute("UPDATE buildings SET level=?,current_hp=?,status='active',completed_at=? WHERE building_id=?",
                               (target_level, hp, now, b['building_id']))
            connection.execute('''UPDATE citizens SET unemployed_since=? WHERE citizen_id IN
                (SELECT citizen_id FROM citizen_assignments WHERE job_id=? AND ended_at IS NULL)''', (now, job['job_id']))
            connection.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='completed' WHERE job_id=? AND ended_at IS NULL",
                               (now, job['job_id']))
            connection.execute('''INSERT INTO building_state_events (building_id,event_type,occurred_at,event_data)
                VALUES (?,'project_completed',?,?)''', (b['building_id'], now, json.dumps({'level': target_level})))
            from game.simulation import _event
            _event(connection,state,'building_project_completed',now,{'building_id':b['building_id'],'building_type':b['building_type'],'job_type':job['job_type'],'level':target_level})
        elif job['job_type'] == 'construction':
            connection.execute('UPDATE buildings SET current_hp=? WHERE building_id=?',
                               (max(0,spec(state, b)['hp'] * done / job['work_required']-json.loads(job['inputs_spent']).get('_damage',0)), b['building_id']))


def validate_placement(connection, state, building):
    w, h = footprint(state, building)
    x, y = building['origin_x'], building['origin_y']
    if x < 0 or y < 0 or x + w > state['config']['map_width'] or y + h > state['config']['map_height']:
        raise ValueError('The whole building must fit inside the map.')
    obstacles = [(b['origin_x'], b['origin_y'], *footprint(state, b)) for b in state['buildings']
                 if b['status'] not in ('cleared', 'demolished')]
    # Every persisted obstacle must be checked, including legacy map records.
    if expanded(state):
        catalog=rules(state)['derelicts']
        obstacles += [(d['origin_x'],d['origin_y'],*catalog[d['derelict_type']]['footprint'])
                      for d in state['derelicts'] if d['status']!='cleared']
    elif state['derelicts']:
        raise ValueError('Derelict placement support is not enabled in this prototype.')
    if any(x < ox + ow and x + w > ox and y < oy + oh and y + h > oy for ox, oy, ow, oh in obstacles):
        raise ValueError('Those tiles are already occupied. Choose an empty footprint.')


def change_building(path, action, *, building_type=None, building_id=None, x=None, y=None,
                    rotation=0, citizen_id=None, expected_level=None, unit_id=None, exposed=False, now=None, auto_builder=False):
    """Each command either commits all spending/history/state, or none of it."""
    from game.simulation import _advance, _event
    now = int(time.time()) if now is None else now
    with closing(connect_database(path)) as connection, connection:
        connection.row_factory = sqlite3.Row
        connection.execute('BEGIN IMMEDIATE')
        state = read_state(connection)
        if not state or state['settlement']['status'] != 'active' or state['season']['status'] == 'finished':
            raise ValueError('This settlement is not active.')
        from game.admin_controls import require_running
        require_running(connection, state)
        if now < state['settlement']['simulation_processed_at']:
            raise ValueError('The clock is earlier than the saved state.')
        if action not in ('build', 'upgrade', 'builder', 'worker', 'release', 'enable', 'enable_housing', 'enable_recovery', 'enable_progression', 'enable_repairs', 'repair', 'repairer', 'enable_support', 'guard', 'patrol', 'release_defense', 'enable_maintenance', 'service_drone', 'repair_drone_auto', 'repair_drone_target', 'repair_drone_off', 'cancel_build', 'demolish', 'enable_structural', 'enable_consequences', 'salvage_ruin', 'expel'):
            raise ValueError('Unknown building action.')
        _advance(connection, state, now)
        state = read_state(connection)
        if state['season']['status'] == 'finished':
            return state
        if state['settlement']['status'] != 'active':
            return state
        changed_at = state['season']['paused_at'] if state['season']['status'] == 'paused' else now
        sid = state['settlement']['settlement_id']
        if action=='enable_structural':
            from game.structural import enable
            enable(connection,state,changed_at)
            return read_state(connection)
        if action=='enable_consequences':
            from game.consequences import enable
            enable(connection,state,changed_at)
            return read_state(connection)
        if action=='salvage_ruin':
            from game.ruins import command
            command(connection,state,building_id,citizen_id,changed_at,exposed)
            return read_state(connection)
        if action=='expel':
            from game.consequences import command
            command(connection,state,citizen_id,changed_at)
            return read_state(connection)
        if action in ('enable_maintenance','service_drone','repair_drone_auto','repair_drone_target','repair_drone_off'):
            from game.maintenance import command
            command(connection,state,action,unit_id,building_id,changed_at)
            return read_state(connection)
        if action in ('cancel_build','demolish'):
            from game.building_management import command
            command(connection,state,action,building_id,changed_at)
            return read_state(connection)
        if action in ('enable_support','guard','patrol','release_defense'):
            from game.support import command
            command(connection,state,action,building_id,citizen_id,changed_at,exposed)
            return read_state(connection)
        if action in ('enable_repairs','repair','repairer'):
            from game.repairs import command
            command(connection,state,action,building_id,citizen_id,changed_at,exposed)
            return read_state(connection)
        if action=='enable_progression':
            from game.progression import enable
            enable(connection,state,changed_at)
            return read_state(connection)
        if action=='enable_recovery':
            from game.recovery import enable
            enable(connection,state,changed_at)
            return read_state(connection)
        if action=='enable_housing':
            from game.population import enable
            enable(connection,state,changed_at)
            return read_state(connection)
        if action=='enable':
            from game.scavenging import enable
            enable(connection,state,changed_at)
            return read_state(connection)
        if building_type in load_config('prototype_v5')['buildings'] and building_type not in load_config('prototype_v4')['buildings']:
            from game.population import enable
            enable(connection,state,changed_at)
            state=read_state(connection)
        if building_type in load_config('prototype_v9')['buildings'] and building_type not in load_config('prototype_v8')['buildings']:
            from game.manufacturing import enable
            enable(connection,state,changed_at)
            state=read_state(connection)
        if building_type in load_config('prototype_v4')['buildings'] and building_type not in rules(state)['buildings']:
            from game.scavenging import enable
            enable(connection,state,changed_at)
            state=read_state(connection)
        if building_type in load_config('prototype_v10')['buildings'] and building_type not in load_config('prototype_v9')['buildings']:
            from game.support import enable
            enable(connection,state,changed_at)
            state=read_state(connection)
        if building_type in ('automated_turret','anti_air_turret'):
            from game.structural import enable
            enable(connection,state,changed_at)
            state=read_state(connection)
        catalog = rules(state)['buildings']
        building = next((b for b in state['buildings'] if b['building_id'] == building_id), None)
        if action in ('build', 'upgrade'):
            if changed_at >= state['season']['finalization_at'] or state['season']['status'] == 'finalizing':
                raise ValueError('New construction and upgrades are closed during the final three hours.')
            if action == 'build':
                if building_type not in catalog or building_type == 'town_hall':
                    raise ValueError('Choose a building from the catalog.')
                if type(x) is not int or type(y) is not int or rotation not in (0, 90):
                    raise ValueError('Choose whole-number map coordinates and a valid orientation.')
                building = dict(building_type=building_type, origin_x=x, origin_y=y, rotation=rotation, level=1)
                validate_placement(connection, state, building)
                target_level = 1
            else:
                if building is None or building['status'] != 'active':
                    raise ValueError('Choose a completed building with no upgrade already in progress.')
                if any(j['target_building_id']==building_id and j['status'] in ('active','paused') for j in state['jobs']):
                    raise ValueError('Finish the current repair project before upgrading.')
                if building['level'] != expected_level:
                    raise ValueError('This building has changed. Reload before upgrading again.')
                target_level = building['level'] + 1
                if target_level > catalog[building['building_type']]['max_level']:
                    raise ValueError('This building is already at its maximum level.')
            if state['buildings'][0]['level'] < catalog[building['building_type']]['unlock']:
                raise ValueError(f"Requires Town Hall level {catalog[building['building_type']]['unlock']}.")
            target = spec(state, building, target_level)
            costs = {r: target[r] for r in ('scrap', 'metal', 'electronics')}
            from game.trading import available
            if any(available(state,r) < cost for r, cost in costs.items()):
                raise ValueError('Not enough building materials. The full cost is required before work starts.')
            if action == 'build':
                building_id = connection.execute('''INSERT INTO buildings
                    (settlement_id,building_type,origin_x,origin_y,rotation,level,current_hp,status,created_at)
                    VALUES (?,?,?,?,?,1,0,'construction',?)''', (sid, building_type, x, y, rotation, changed_at)).lastrowid
            else:
                connection.execute("UPDATE buildings SET status='upgrading' WHERE building_id=?", (building_id,))
            connection.execute('''UPDATE settlement_resources SET scrap=scrap-?,metal=metal-?,
                electronics=electronics-?,updated_at=? WHERE settlement_id=?''',
                (costs['scrap'], costs['metal'], costs['electronics'], changed_at, sid))
            connection.execute('''INSERT INTO settlement_jobs
                (settlement_id,job_type,target_type,target_building_id,work_required,status,
                 created_at,last_processed_at,inputs_spent,pause_reason)
                VALUES (?,?,'building',?,?,'paused',?,?,?,'Assign builders')''',
                (sid, 'construction' if action == 'build' else 'upgrade', building_id,
                 target['minutes'] * 60, changed_at, changed_at, json.dumps(costs)))
            if action=='build' and auto_builder and coverage(state,building)>=rules(state)['construction']['coverage_fraction']:
                # Never take an Administrator/worker, or authorize dangerous exposure.
                eligible=sorted((c for c in state['citizens'] if c['assignment']=='unassigned'
                                 and c['current_hp']>0 and not c.get('away')),key=lambda c:c['citizen_id'])
                for candidate in eligible:
                    if connection.execute('SELECT 1 FROM attack_citizens WHERE citizen_id=? AND released_at IS NULL',(candidate['citizen_id'],)).fetchone():
                        continue
                    job_id=connection.execute('SELECT job_id FROM settlement_jobs WHERE target_building_id=? AND job_type=\'construction\' AND status=\'paused\' ORDER BY job_id DESC LIMIT 1',(building_id,)).fetchone()[0]
                    citizen_id=candidate['citizen_id']
                    connection.execute('''INSERT INTO citizen_assignments
                        (citizen_id,settlement_id,assignment_type,building_id,job_id,assigned_at)
                        VALUES (?,?,'construction',?,?,?)''',(citizen_id,sid,building_id,job_id,changed_at))
                    connection.execute('UPDATE citizens SET unemployed_since=NULL WHERE citizen_id=?',(citizen_id,))
                    connection.execute("UPDATE settlement_jobs SET pause_reason=NULL WHERE job_id=?",(job_id,))
                    _event(connection,state,'prototype_builder_auto_assigned',changed_at,
                           {'building_id':building_id,'citizen_id':citizen_id,'job_id':job_id})
                    break
        else:
            citizen = next((c for c in state['citizens'] if c['citizen_id'] == citizen_id), None)
            if not citizen or citizen['current_hp'] <= 0:
                raise ValueError('Choose a living citizen from this settlement.')
            if connection.execute('SELECT 1 FROM attack_citizens WHERE citizen_id=? AND released_at IS NULL', (citizen_id,)).fetchone():
                raise ValueError('That citizen is away from the settlement.')
            if action == 'release':
                if citizen['assignment'] not in ('construction', 'production','repair','scavenging') or citizen['building_id'] != building_id:
                    raise ValueError('That citizen is not assigned to this building.')
                connection.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='released' WHERE assignment_id=?",
                                   (changed_at, citizen['assignment_id']))
                connection.execute('UPDATE citizens SET unemployed_since=? WHERE citizen_id=?', (changed_at, citizen_id))
            else:
                if building is None or building['status'] not in ('construction', 'active', 'upgrading'):
                    raise ValueError('Choose an available building.')
                kind = 'construction' if action == 'builder' else 'production'
                if citizen['assignment'] == kind and citizen['building_id'] == building_id:
                    return state  # A repeated staffing submission changes nothing.
                moving_admin=citizen['assignment']=='administrator' and state['season']['config_version']=='prototype_v13'
                if citizen['assignment'] != 'unassigned' and not moving_admin:
                    raise ValueError('Release this citizen from their current job first.')
                job = next((j for j in state['jobs'] if j['target_building_id'] == building_id and j['status'] in ('active', 'paused')), None)
                if action == 'builder' and job and job['job_type']=='repair':
                    raise ValueError('Assign repair workers to this project.')
                if action == 'builder' and job and job['job_type'] not in ('construction','upgrade'):
                    raise ValueError('Choose a construction or upgrade project.')
                if action == 'builder' and job is None:
                    raise ValueError('This building has no construction project.')
                if action == 'worker':
                    if building['building_type']=='guard_post':raise ValueError('Use the Guard assignment for Guard Posts.')
                    if building['building_type'] == 'town_hall' or building['status'] != 'active':
                        raise ValueError('Workers need a completed production building.')
                    count = sum(c['assignment'] == 'production' and c['building_id'] == building_id for c in state['citizens'])
                    if count >= spec(state, building)['workers']:
                        raise ValueError('All production worker slots are filled.')
                needs_oxygen = action=='builder' or building['building_type'] in ('garden','greenhouse','hydroponics') or not expanded(state) or catalog[building['building_type']]['oxygen_required']
                if needs_oxygen and building['building_type'] != 'town_hall' and coverage(state, building) < rules(state)['construction']['coverage_fraction']:
                    if not exposed or 'consequences' not in state['config']:raise ValueError('Danger: outside Oxygen. Confirm exposure before assigning this worker.')
                if moving_admin:
                    connection.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='reassigned' WHERE assignment_id=?",(changed_at,citizen['assignment_id']))
                assignment=connection.execute('''INSERT INTO citizen_assignments
                    (citizen_id,settlement_id,assignment_type,building_id,job_id,assigned_at) VALUES (?,?,?,?,?,?)''',
                    (citizen_id, sid, kind, building_id, job['job_id'] if action == 'builder' else None, changed_at)).lastrowid
                if exposed and 'consequences' in state['config'] and coverage(state,building)<rules(state)['construction']['coverage_fraction']:
                    from game.consequences import authorize
                    authorize(connection,state,assignment,changed_at)
                connection.execute('UPDATE citizens SET unemployed_since=NULL WHERE citizen_id=?', (citizen_id,))
        if state['season']['config_version'] not in ('prototype_v3','prototype_v4','prototype_v5','prototype_v6','prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
            connection.execute("UPDATE seasons SET config_version='prototype_v3' WHERE season_id=?", (state['season']['season_id'],))
            _event(connection, state, 'prototype_config_enabled', changed_at, {'from': state['season']['config_version'], 'to': 'prototype_v3'})
        _event(connection, state, 'prototype_building_action', changed_at,
               {'action': action, 'building_id': building_id, 'citizen_id': citizen_id})
        from game.population import rebalance
        if state['season']['config_version']=='prototype_v13':
            from game.consequences import replace_admin
            replace_admin(connection,read_state(connection),changed_at)
        rebalance(connection,read_state(connection),changed_at)
        return read_state(connection)

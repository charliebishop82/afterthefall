"""Server-authoritative elapsed-time resources, jobs and citizen consequences.

No timers run in the background. Each request settles elapsed time atomically.
Legacy configurations freeze on depletion; current games apply supply health rules.
"""

from contextlib import closing
from contextvars import ContextVar
import json
import math
import sqlite3
import time

from database.create_database import connect_database
from game.settlement import load_config, read_state
from game import buildings

FINALIZING = ContextVar('finalizing_shared_season', default=False)


def finish_shared_season(connection, state, now):
    """Settle every player before publishing the shared finished state."""
    from game.settlement import CURRENT_ACCOUNT, account_scope
    from game.combat import RESOLVING, resolve_due
    if (CURRENT_ACCOUNT.get() is None or FINALIZING.get() or RESOLVING.get()
            or not state or state['season']['status'] not in ('active', 'finalizing')
            or now < state['season']['ends_at']):
        return False
    token = FINALIZING.set(True)
    try:
        end = state['season']['ends_at']
        season_id = state['season']['season_id']
        resolve_due(connection, state, end)
        players = connection.execute('SELECT account_id FROM settlements WHERE season_id=? ORDER BY settlement_id', (season_id,)).fetchall()
        snapshots = {}
        for player in players:
            with account_scope(player['account_id']):
                current = read_state(connection)
                _advance(connection, current, end)
                current = read_state(connection)
                sid = current['settlement']['settlement_id']
                from game.expeditions import finish as finish_expeditions
                finish_expeditions(connection,current,end)
                current=read_state(connection)
                if current.get('expansion'):
                    from game.banking import finish as finish_banking
                    finish_banking(connection,current,end)
                    current=read_state(connection)
                snapshots[str(sid)] = current['resources']
                connection.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='season_finished' WHERE ended_at IS NULL AND job_id IN (SELECT job_id FROM settlement_jobs WHERE settlement_id=? AND status IN ('queued','active','paused'))", (end, sid))
                connection.execute("UPDATE settlement_jobs SET status='cancelled',pause_reason='Season finished' WHERE settlement_id=? AND status IN ('queued','active','paused')", (sid,))
                from game.maintenance import finish as finish_maintenance
                finish_maintenance(connection,current,end)
                connection.execute("UPDATE settlements SET status='archived' WHERE settlement_id=?", (sid,))
                _event(connection, current, 'prototype_season_finished', end, current['resources'])
        from game.market import finish_season as finish_market
        finish_market(connection,season_id,end)
        connection.execute("UPDATE seasons SET status='finished',final_snapshot=? WHERE season_id=?", (json.dumps({'settlement_resources': snapshots}), season_id))
        return True
    finally:
        FINALIZING.reset(token)


def resource_rates(state):
    """Potential per-hour rates. Pausing does not change the displayed plan."""
    if state['season']['config_version'] in ('prototype_v3','prototype_v4','prototype_v5','prototype_v6','prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
        return buildings.resource_rates(state)
    config = state['config']
    rules = config.get('simulation') or load_config('prototype_v2')['simulation']
    hall = state['buildings'][0]
    condition = min(1.0, hall['current_hp'] / config['town_hall']['hp'])
    worker = next((c for c in state['citizens'] if c['assignment'] == 'administrator'), None)
    productivity = 0
    if worker and worker['current_hp'] > 0 and hall['status'] == 'active':
        max_hp = config['citizen_hp'] + (worker['level'] - 1) * rules['hp_per_level']
        health = min(1.0, worker['current_hp'] / max_hp)
        morale = next(factor for upper, factor in rules['morale_bands'] if worker['morale'] < upper)
        productivity = health * morale * (1 + (worker['level'] - 1) * rules['productivity_per_level'])
    result = {}
    for resource in ('food', 'water'):
        production = rules[f'town_hall_{resource}_per_hour'] * productivity * condition
        consumption = sum(not c.get('away') for c in state['citizens']) * rules[f'{resource}_per_citizen_per_hour']
        net = production - consumption
        quantity = state['resources'][resource]
        capacity = config['town_hall'][f'{resource}_storage'] * condition
        hours = quantity / -net if net < 0 else None
        result[resource] = {'production': production, 'consumption': consumption, 'net': net,
                            'capacity': capacity, 'hours_to_empty': hours}
    return result


def _event(connection, state, kind, now, data):
    event_id=connection.execute('''INSERT INTO game_events
        (season_id,settlement_id,event_type,occurred_at,event_data) VALUES (?,?,?,?,?)''',
        (state['season']['season_id'], state['settlement']['settlement_id'], kind, now, json.dumps(data))).lastrowid
    from game.notifications import event
    event(connection,state,kind,now,data,event_id)


def _advance(connection, state, now):
    from game.admin_controls import frozen
    if frozen(connection, state):
        return
    if finish_shared_season(connection, state, now):
        return
    from game.expeditions import synchronize as expedition_sync
    if state and expedition_sync(connection,state,state['settlement']['simulation_processed_at']):state=read_state(connection)
    from game.diplomacy import synchronize as treaty_sync
    if state:treaty_sync(connection,state,now)
    from game.combat import resolve_due,daily
    if resolve_due(connection,state,now):state=read_state(connection)
    from game.consequences import synchronize as citizen_sync
    if state and citizen_sync(connection,state,state['settlement']['simulation_processed_at']):state=read_state(connection)
    from game.needs import synchronize
    if state and synchronize(connection,state,state['settlement']['simulation_processed_at']):state=read_state(connection)
    from game.expansion import boundary as expansion_boundary
    if state and expansion_boundary(connection,state,state['settlement']['simulation_processed_at']):state=read_state(connection)
    from game.consequences import daily as citizen_daily
    if state and citizen_daily(connection,state,state['settlement']['simulation_processed_at']):state=read_state(connection)
    if state and daily(connection,state,state['settlement']['simulation_processed_at']):state=read_state(connection)
    from game.trading import expire
    if state:
        expiry_time=state['settlement']['simulation_processed_at'] if state['settlement']['status']=='active' and state['season']['status'] in ('active','finalizing') else now
        if expire(connection,state,expiry_time):state=read_state(connection)
    while state and state['season']['status'] in ('active', 'finalizing') and state['settlement']['status'] == 'active':
        start = state['settlement']['simulation_processed_at']
        if now <= start:
            return
        from game.maintenance import prepare as prepare_maintenance
        if prepare_maintenance(connection,state,start):state=read_state(connection)
        from game.manufacturing import prepare
        if prepare(connection,state,start):state=read_state(connection)
        _advance_interval(connection, state, now)
        state = read_state(connection)
        if expedition_sync(connection,state,state["settlement"]["simulation_processed_at"]):state=read_state(connection)
        if synchronize(connection,state,state['settlement']['simulation_processed_at']):state=read_state(connection)
        if citizen_sync(connection,state,state['settlement']['simulation_processed_at']):state=read_state(connection)
        if expansion_boundary(connection,state,state['settlement']['simulation_processed_at']):state=read_state(connection)
        from game.consequences import daily as citizen_daily
        if citizen_daily(connection,state,state['settlement']['simulation_processed_at']):state=read_state(connection)
        if daily(connection,state,state['settlement']['simulation_processed_at']):state=read_state(connection)
        if expire(connection,state,state['settlement']['simulation_processed_at']):
            state = read_state(connection)
        if state['settlement']['simulation_processed_at'] == start:
            break
    if state and state['settlement']['status'] != 'active':
        expire(connection,state,now)


def _advance_interval(connection, state, now):
    if state is None or state['season']['status'] not in ('active', 'finalizing'):
        return
    if state['settlement']['status'] != 'active':
        return
    start = state['settlement']['simulation_processed_at']
    if now <= start:
        return  # Repeated reads and backwards clock adjustments never double-process.
    target = min(now, state['season']['ends_at'])
    from game.settlement import CURRENT_ACCOUNT
    if CURRENT_ACCOUNT.get() is not None:target=min(target,(start//86400+1)*86400)
    from game.expeditions import next_boundary as expedition_boundary
    expedition_at=expedition_boundary(state)
    if expedition_at is not None:target=min(target,expedition_at)
    from game.trading import next_expiry,available
    expires_at=next_expiry(connection,state)
    if expires_at is not None:target=min(target,expires_at)
    from game.recovery import next_boundary
    recovery_at=next_boundary(state)
    if recovery_at is not None:
        target=min(target,recovery_at)
    from game.progression import next_boundary as xp_boundary
    xp_at=xp_boundary(state)
    if xp_at is not None:target=min(target,xp_at)
    from game.repairs import next_boundary as repair_boundary
    repair_at=repair_boundary(state)
    if repair_at is not None:target=min(target,repair_at)
    from game.needs import next_boundary as needs_boundary
    needs_at=needs_boundary(state)
    if needs_at is not None:target=min(target,needs_at)
    from game.manufacturing import next_boundary as military_boundary
    military_at=military_boundary(state)
    if military_at is not None:target=min(target,military_at)
    from game.consequences import next_boundary as citizen_boundary
    citizen_at=citizen_boundary(state)
    if citizen_at is not None:target=min(target,citizen_at)
    if state.get('expansion'):
        from game.banking import investments
        for investment in investments(connection,state['settlement']['settlement_id']):
            if investment['matures_at']>start:target=min(target,investment['matures_at'])
    completion = buildings.next_completion(state)
    if completion is not None:
        target = min(target, start + completion)
    if target < start:
        raise ValueError('The saved season end precedes its processed time.')
    rates = resource_rates(state)
    if buildings.expanded(state):
        for resource in ('scrap','metal','electronics'):
            if rates[resource]['net']<0 and available(state,resource)>1e-8:
                target=min(target,start+max(1,math.ceil(available(state,resource)/-rates[resource]['net']*3600)))
        # Restart waiting conversion plants at the first whole second of input
        # recovery, even during one long offline request.
        if any(s['reason']=='Waiting for input materials' for s in buildings.operating_status(state).values()):
            if any(available(state,r)<=1e-8 and rates[r]['production']>0 for r in ('scrap','metal')):
                target=min(target,start+1)
    depleted_at = None
    for resource, rate in rates.items():
        if resource not in ('food','water'):
            continue
        if rate['net'] < 0:
            # UTC timestamps are whole seconds; settle the first depletion boundary.
            quantity=available(state,resource)
            if buildings.expanded(state) and resource=='food':
                from game.economy import available_food
                quantity=available_food(state)
            from game.needs import enabled as needs_enabled
            if needs_enabled(state) and quantity<=1e-8:
                continue
            seconds = math.ceil(min(quantity, rate['capacity']) / -rate['net'] * 3600)
            boundary = start + seconds
            depleted_at = boundary if depleted_at is None else min(depleted_at, boundary)
    if depleted_at is not None:
        target = min(target, depleted_at)
    elapsed_hours = (target - start) / 3600
    amounts = {}
    for resource, rate in rates.items():
        initial = min(state['resources'][resource], rate['capacity'])
        amounts[resource] = max(0.0, min(rate['capacity'], initial + rate['net'] * elapsed_hours))
    if buildings.expanded(state):
        from game.economy import advance_resources
        amounts=advance_resources(connection,state,target-start,target)
    else:
        connection.execute('''UPDATE settlement_resources SET food=?,water=?,updated_at=?
                          WHERE settlement_id=?''',
                       (amounts['food'], amounts['water'], target, state['settlement']['settlement_id']))
    connection.execute('UPDATE settlements SET simulation_processed_at=? WHERE settlement_id=?',
                       (target, state['settlement']['settlement_id']))
    from game.recovery import accrue
    accrue(connection,state,target-start,target)
    from game.progression import accrue as accrue_xp
    accrue_xp(connection,state,target-start,target)
    from game.needs import accrue as accrue_needs
    accrue_needs(connection,state,target-start,target)
    from game.consequences import accrue as citizen_accrue
    citizen_accrue(connection,state,target-start,target)
    buildings.progress_jobs(connection, state, target - start, target)
    from game.repairs import regenerate
    regenerate(connection,state,target-start,target)
    from game.population import rebalance
    rebalance(connection,read_state(connection),target)
    if target == state['season']['ends_at']:
        # Shared finalization runs after every participant has reached the end.
        from game.settlement import CURRENT_ACCOUNT
        if CURRENT_ACCOUNT.get() is not None:
            return
        connection.execute('''UPDATE citizen_assignments SET ended_at=?,end_reason='season_finished'
            WHERE ended_at IS NULL AND job_id IN
            (SELECT job_id FROM settlement_jobs WHERE settlement_id=? AND status IN ('queued','active','paused'))''',
            (target, state['settlement']['settlement_id']))
        connection.execute('''UPDATE settlement_jobs SET status='cancelled',pause_reason='Season finished'
            WHERE settlement_id=? AND status IN ('queued','active','paused')''', (state['settlement']['settlement_id'],))
        connection.execute("UPDATE seasons SET status='finished',final_snapshot=? WHERE season_id=?",
                           (json.dumps({'prototype_resources': amounts}), state['season']['season_id']))
        from game.maintenance import finish as finish_maintenance
        finish_maintenance(connection,state,target)
        connection.execute("UPDATE settlements SET status='archived' WHERE settlement_id=?",
                           (state['settlement']['settlement_id'],))
        _event(connection, state, 'prototype_season_finished', target, amounts)
    elif depleted_at is not None and target == depleted_at:
        from game.needs import enabled as needs_enabled
        if needs_enabled(state):return
        from game.settlement import CURRENT_ACCOUNT
        if CURRENT_ACCOUNT.get() is not None:
            connection.execute("UPDATE settlements SET status='suspended',suspended_at=? WHERE settlement_id=?",(target,state['settlement']['settlement_id']))
        else:
            connection.execute("UPDATE seasons SET status='paused',paused_at=? WHERE season_id=?",
                               (target, state['season']['season_id']))
        _event(connection, state, 'prototype_supply_pause', target, amounts)


def advance_settlement(path, now=None):
    now = int(time.time()) if now is None else now
    with closing(connect_database(path)) as connection, connection:
        connection.row_factory = sqlite3.Row
        connection.execute('BEGIN IMMEDIATE')
        state = read_state(connection)
        if state:
            from game.trading import settle_incoming
            if settle_incoming(connection,state,now):state=read_state(connection)
        _advance(connection, state, now)
        return read_state(connection)


def apply_action(path, action, citizen_id=None, now=None):
    """Validate first, then settle old rates before changing staffing or the clock."""
    now = int(time.time()) if now is None else now
    with closing(connect_database(path)) as connection, connection:
        connection.row_factory = sqlite3.Row
        connection.execute('BEGIN IMMEDIATE')
        state = read_state(connection)
        if state is None:
            raise ValueError('Create a settlement first.')
        if action not in ('resume', 'pause', 'assign'):
            raise ValueError('Unknown settlement action.')
        from game.admin_controls import require_running
        require_running(connection, state)
        if state['season']['status'] == 'finished' or state['settlement']['status'] != 'active':
            raise ValueError('This settlement is not active.')
        if now < state['settlement']['simulation_processed_at']:
            raise ValueError('The clock is earlier than the saved state. Try again when it catches up.')
        candidate = None
        if action == 'assign':
            candidate = next((c for c in state['citizens'] if c['citizen_id'] == citizen_id), None)
            if candidate is None or candidate['current_hp'] <= 0:
                raise ValueError('Choose a living citizen from this settlement.')
            if candidate['assignment'] not in ('unassigned', 'administrator'):
                raise ValueError('That citizen already has another assignment.')
            if connection.execute('SELECT 1 FROM attack_citizens WHERE citizen_id=? AND released_at IS NULL',
                                  (citizen_id,)).fetchone():
                raise ValueError('That citizen is away from the settlement.')
        _advance(connection, state, now)
        state = read_state(connection)
        if state['season']['status'] == 'finished':
            return state  # Keep the season-end transition, do not apply the requested action.
        if state['settlement']['status'] != 'active':
            return state  # Persist a reached supply freeze without applying staffing.
        if action == 'assign':
            candidate = next((c for c in state['citizens'] if c['citizen_id'] == citizen_id), None)
            if candidate is None or candidate['current_hp'] <= 0 or candidate.get('away'):
                raise ValueError('This citizen is no longer available. Reload the settlement.')
        sid = state['settlement']['settlement_id']
        season_id = state['season']['season_id']
        if action == 'resume' and state['season']['status'] == 'paused':
            food=state['resources']['food']
            if buildings.expanded(state):
                from game.economy import available_food
                food=available_food(state)
            if min(food, state['resources']['water']) <= 0:
                raise ValueError('Supplies are empty. This prototype stays paused until supply recovery is implemented.')
            paused_at = state['season']['paused_at']
            if paused_at is None or now < paused_at:
                raise ValueError('The saved pause time is invalid.')
            paused_seconds = now - paused_at
            from game.recovery import shift_clock
            shift_clock(connection,state,paused_seconds,now)
            # This is an explicit configuration transition, not a schema migration.
            if state['season']['config_version'] == 'prototype_v1':
                connection.execute("UPDATE seasons SET config_version='prototype_v2' WHERE season_id=?", (season_id,))
                _event(connection, state, 'prototype_config_enabled', now,
                       {'from': 'prototype_v1', 'to': 'prototype_v2'})
            connection.execute('''UPDATE seasons SET status='active',paused_at=NULL,
                finalization_at=finalization_at+?,ends_at=ends_at+? WHERE season_id=?''',
                (paused_seconds, paused_seconds, season_id))
            connection.execute('''UPDATE settlements SET simulation_processed_at=?,
                protection_until=protection_until+? WHERE settlement_id=?''', (now, paused_seconds, sid))
            connection.execute('''UPDATE citizens SET unemployed_since=unemployed_since+?,
                homeless_since=homeless_since+? WHERE settlement_id=?''', (paused_seconds, paused_seconds, sid))
            _event(connection, state, 'prototype_time_resumed', now, {})
        elif action == 'pause' and state['season']['status'] in ('active', 'finalizing'):
            connection.execute("UPDATE seasons SET status='paused',paused_at=? WHERE season_id=?", (now, season_id))
            _event(connection, state, 'prototype_time_paused', now, {})
        elif action == 'assign' and candidate['assignment'] != 'administrator':
            # Paused time is frozen. Record a paused reassignment at its freeze boundary.
            changed_at = state['season']['paused_at'] if state['season']['status'] == 'paused' else now
            current = connection.execute('''SELECT assignment_id,citizen_id FROM citizen_assignments
                WHERE settlement_id=? AND assignment_type='administrator' AND ended_at IS NULL''', (sid,)).fetchall()
            for old in current:
                connection.execute("UPDATE citizen_assignments SET ended_at=?,end_reason='reassigned' WHERE assignment_id=?",
                                   (changed_at, old['assignment_id']))
                connection.execute('UPDATE citizens SET unemployed_since=? WHERE citizen_id=?',
                                   (changed_at, old['citizen_id']))
            connection.execute('''INSERT INTO citizen_assignments
                (citizen_id,settlement_id,assignment_type,building_id,assigned_at)
                VALUES (?,?,'administrator',?,?)''', (citizen_id, sid, state['buildings'][0]['building_id'], changed_at))
            connection.execute('UPDATE citizens SET unemployed_since=NULL WHERE citizen_id=?', (citizen_id,))
            _event(connection, state, 'prototype_administrator_changed', changed_at, {'citizen_id': citizen_id})
        return read_state(connection)

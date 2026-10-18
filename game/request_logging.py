"""Bounded JSON request history; never log raw forms, cookies or exceptions."""
from contextlib import closing
from datetime import datetime, timezone
import json
import logging
from logging.handlers import RotatingFileHandler
import math
from pathlib import Path
import sqlite3
import time
import traceback
import uuid

from flask import g, request


NUMERIC_FIELDS = {
    'citizen_id', 'drone_id', 'derelict_id', 'building_id', 'unit_id',
    'target_id', 'recipient_id', 'job_id', 'trade_id', 'listing_id',
    'expedition_id', 'loan_id', 'investment_id', 'treaty_id', 'message_id', 'post_id',
    'x', 'y', 'rotation', 'expected_level', 'quantity', 'unit_price',
    'amount', 'days', 'missile_count', 'offered_quantity', 'requested_quantity',
}
RESOURCES = {'food', 'water', 'scrap', 'metal', 'electronics', 'credits'}
ACTIONS = {
    'assign', 'release', 'build', 'upgrade', 'builder', 'worker', 'repair',
    'repairer', 'guard', 'patrol', 'release_defense', 'service_drone',
    'repair_drone_auto', 'repair_drone_target', 'repair_drone_off',
    'cancel_build', 'demolish', 'salvage_ruin', 'expel', 'enable',
    'enable_housing', 'enable_recovery', 'enable_progression', 'enable_repairs',
    'enable_support', 'enable_maintenance', 'enable_structural',
    'enable_consequences', 'propose', 'accept', 'reject', 'cancel', 'launch',
    'equipment_buy', 'equipment_sell', 'equipment_reserve_buy',
    'sell', 'reserve_buy', 'declare', 'war', 'withdraw', 'borrow', 'repay', 'invest', 'list', 'buy',
    'recall', 'send', 'post', 'archive', 'report', 'order', 'stop', 'rations', 'set',
    'queue', 'cancel_order', 'archive_message', 'archive_post',
}
ENUM_FIELDS = {
    'resource': RESOURCES, 'offered_resource': RESOURCES,
    'requested_resource': RESOURCES,
    'food': {'full', 'reduced', 'emergency'},
    'water': {'full', 'reduced', 'emergency'},
    'objective': {'balanced', 'food', 'water', 'scrap', 'metal',
                  'electronics', 'infrastructure', 'population', 'credits'},
    'unit_type': {'offensive_drone', 'air_defense_drone',
                  'ground_defense_drone', 'repair_drone', 'missile', 'interceptor'},
    'treaty_type': {'peace', 'non_aggression', 'trade', 'mutual_defense', 'full_defense'},
    'building_type': {'starter_offensive_hangar','starter_air_defense_bay','starter_ground_defense_bay','starter_engineering_workshop','starter_missile_silo','starter_interceptor_battery','greenhouse', 'garden', 'hydroponics', 'drone_factory', 'oxygen_garden', 'air_defense_bay', 'salvage_depot', 'shack', 'trading_post', 'water_tank', 'wind_turbine', 'rain_collector', 'generator_plant', 'automated_turret', 'munitions_factory', 'recycler', 'house', 'root_cellar', 'ground_defense_bay', 'offensive_hangar', 'warehouse', 'cold_storage', 'solar_array', 'pup_tent', 'industrial_oxygen', 'oxygen_generator', 'missile_silo', 'engineering_workshop', 'clinic', 'vault', 'medical_center', 'electronics_fabricator', 'interceptor_battery', 'scrap_yard', 'apartment_block', 'anti_air_turret', 'town_hall', 'guard_post', 'community_center', 'purification_plant', 'upgraded_tent', 'well_pump'},
    'repeat': {'0', '1'}, 'exposed': {'0', '1'},
}


def safe_parameters(form):
    """Only known enums and bounded numeric metadata can reach the log."""
    result = {}
    numeric=NUMERIC_FIELDS | {'food','water'}
    for key in numeric:
        if key not in form:
            continue
        values = []
        for value in form[key][:64]:
            try:
                number = float(value)
                if math.isfinite(number) and abs(number) <= 10**12:
                    values.append(int(number) if number.is_integer() else number)
            except (ValueError, TypeError, OverflowError):
                pass
        if values:
            result[key] = values if len(values) > 1 else values[0]
    for key, allowed in ENUM_FIELDS.items():
        values = form.get(key, [])
        if len(values) == 1 and values[0] in allowed:
            result[key] = values[0]
    return result


def mark_error(error):
    g.player_error_type = type(error).__name__
    # Clock errors have a useful stable diagnosis. Never copy arbitrary messages.
    if isinstance(error, ValueError) and 'clock is earlier than' in str(error).lower():
        g.player_error_code = 'clock_before_saved_state'
    else:
        g.player_error_code = 'request_rejected' if isinstance(error, (ValueError, PermissionError)) else 'server_error'
    g.player_error_frames = [
        {'file': Path(frame.filename).name, 'line': frame.lineno, 'function': frame.name}
        for frame in traceback.extract_tb(error.__traceback__)[-12:]
    ]


def install_request_logging(app, database, log_path, clock):
    logger = logging.Logger('player-actions', level=logging.INFO)
    if log_path is not None:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=10_000_000, backupCount=5,
                                      encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
    else:
        logger.addHandler(logging.NullHandler())
    app.extensions['player_logger'] = logger
    if log_path is None:
        return

    def safe_route():
        route = request.url_rule.rule if request.url_rule else '(unknown route)'
        if route == '/<path:route>':
            return request.path if request.path in app.config['PLAYER_LOG_ROUTES'] else '(unknown route)'
        return route

    @app.before_request
    def start_request_history():
        g.player_request_id = uuid.uuid4().hex
        g.player_started = time.perf_counter()
        g.player_received_at = int(clock())
        logger.info(json.dumps({
            'event': 'request_started',
            'timestamp_utc': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
            'request_id': g.player_request_id, 'database': Path(database).name,
            'received_at': g.player_received_at, 'method': request.method,
            'route': safe_route(),
        }))

    @app.after_request
    def finish_request_history(response):
        actor = g.get('actor') or {}
        account_id = g.get('player_account_id') or actor.get('account_id')
        route = safe_route()
        form = g.get('form', {})
        supplied_action = form.get('action', [''])[0]
        record = {
            'event': 'request_finished',
            'timestamp_utc': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
            'request_id': g.player_request_id, 'database': Path(database).name,
            'received_at': g.player_received_at,
            'action_timestamp': g.get('player_action_timestamp'),
            'account_id': account_id, 'method': request.method, 'route': route,
            'action': supplied_action if supplied_action in ACTIONS else
                      ('(unknown action)' if supplied_action else None),
            'parameters': safe_parameters(form), 'status': response.status_code,
            'outcome': 'rejected' if response.status_code >= 400 else 'completed',
            'duration_ms': round((time.perf_counter() - g.player_started) * 1000, 3),
        }
        if g.get('catchup_metrics'):
            record['catchup_calculations'] = g.catchup_metrics
        for key in ('player_error_type', 'player_error_code', 'player_error_frames'):
            if g.get(key) is not None:
                record[key.removeprefix('player_')] = g.get(key)
        if log_path is not None and account_id is not None:
            try:
                with closing(sqlite3.connect(Path(database).as_uri() + '?mode=ro', uri=True,
                                             timeout=0.25)) as connection:
                    row = connection.execute(
                        'SELECT settlement_id,season_id,simulation_processed_at '
                        'FROM settlements WHERE account_id=? ORDER BY season_id DESC LIMIT 1',
                        (account_id,)).fetchone()
                    if row:
                        record.update(settlement_id=row[0], season_id=row[1],
                                      saved_clock_observed_at_completion=row[2])
            except sqlite3.Error:
                record['saved_clock_lookup'] = 'unavailable'
        # Includes authentication, handler work, lock waits and completion metadata
        # lookup; excludes Waitress queueing and the final log write/network send.
        duration=(time.perf_counter()-g.player_started)*1000
        waiting=g.get('gameplay_lock_wait_ms',0)
        record.update(duration_ms=round(duration,3),gameplay_lock_wait_ms=round(waiting,3),
                      processing_ms=round(max(0,duration-waiting),3),
                      gameplay_processing_ms=round(g.get('gameplay_processing_ms',0),3),
                      slow_request=duration>=1000,lock_contention=waiting>=250)
        response.headers['Server-Timing']=f'app;dur={duration:.3f}, game_lock;dur={waiting:.3f}'
        logger.info(json.dumps(record, ensure_ascii=True, allow_nan=False))
        response.headers['X-Request-ID'] = g.player_request_id
        return response

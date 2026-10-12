"""Legacy local initialization and account-scoped snapshots of shared settlements."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time
from contextvars import ContextVar
from contextlib import contextmanager
from functools import lru_cache

CURRENT_ACCOUNT=ContextVar("current_account",default=None)

@contextmanager
def account_scope(account_id):
    token=CURRENT_ACCOUNT.set(account_id)
    try:yield
    finally:CURRENT_ACCOUNT.reset(token)


from database.create_database import SCHEMA_VERSION, connect_database, create_database

ROOT = Path(__file__).resolve().parents[1]
CONFIG_VERSION = 'prototype_v1'
LOCAL_USERNAME = '__local_prototype__'


@lru_cache(maxsize=13)
def _config_text(path):
    """Read versioned rules once per process; restart after changing settings."""
    return path.read_text(encoding='utf-8')


def load_config(version=CONFIG_VERSION):
    # Only explicitly supported versions may be loaded, never arbitrary paths.
    if version not in ('prototype_v1', 'prototype_v2', 'prototype_v3', 'prototype_v4', 'prototype_v5', 'prototype_v6','prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
        raise ValueError('This save uses an unsupported configuration version.')
    # Parse afresh so state snapshots and tests cannot mutate shared rules.
    return json.loads(_config_text(ROOT / 'config' / f'{version}.json'))


def prepare_database(path):
    """Create a missing file, but never reset or migrate an existing database."""
    path = Path(path)
    if not path.exists():
        try:
            create_database(path)
        except FileExistsError:
            pass  # Another local launch may have just created it.
    with closing(connect_database(path)) as connection:
        if connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
            raise ValueError('Unsupported database schema. Choose a new prototype database path.')
        # Reading state also rejects unrelated existing saves before serving them.
        _existing_settlement(connection)


def _existing_settlement(connection):
    if CURRENT_ACCOUNT.get() is not None:
        row=connection.execute('SELECT settlement_id FROM settlements WHERE account_id=? ORDER BY season_id DESC LIMIT 1',(CURRENT_ACCOUNT.get(),)).fetchone()
        return row[0] if row else None
    rows = connection.execute('''
        SELECT s.settlement_id, se.config_version, a.username
        FROM settlements s JOIN seasons se USING (season_id)
        JOIN accounts a USING (account_id)
    ''').fetchall()
    if not rows:
        if connection.execute('SELECT count(*) FROM accounts').fetchone()[0] or \
                connection.execute('SELECT count(*) FROM seasons').fetchone()[0]:
            raise ValueError('This database contains other game data. Use a separate prototype save.')
        return None
    if len(rows) != 1 or rows[0][2] != LOCAL_USERNAME:
        raise ValueError('This is not a single-settlement prototype save.')
    load_config(rows[0][1])
    return rows[0][0]


def create_settlement(path, name, now=None):
    """Atomically initialize once; repeated submissions return the existing save."""
    if not isinstance(name, str):
        raise ValueError('Enter a settlement name.')
    name = name.strip()
    if not 1 <= len(name) <= 40 or any(ord(char) < 32 for char in name):
        raise ValueError('Use a settlement name of 1–40 characters without control characters.')
    config = load_config()
    now = int(time.time()) if now is None else now
    hall = config['town_hall']
    x = (config['map_width'] - hall['width']) // 2
    y = (config['map_height'] - hall['height']) // 2
    with closing(connect_database(path)) as connection, connection:
        connection.execute('BEGIN IMMEDIATE')
        existing = _existing_settlement(connection)
        if existing is not None:
            return existing
        account_id = connection.execute('''INSERT INTO accounts
            (username,password_hash,display_name,created_at,is_active)
            VALUES (?, '!', 'Local player', ?, 0)''', (LOCAL_USERNAME, now)).lastrowid
        end = now + config['season_days'] * 86400
        season_id = connection.execute('''INSERT INTO seasons
            (name,status,scheduled_start_at,started_at,finalization_at,ends_at,
             created_at,config_version,map_seed,paused_at)
            VALUES ('Local prototype','paused',?,?,?,?,?,?, 'prototype-map-1',?)''',
            (now, now, end - config['finalization_hours'] * 3600, end, now,
             config['version'], now)).lastrowid
        return seed_settlement(connection,account_id,season_id,name,config,now,x,y)


def read_settlement(path):
    """Return a consistent view of persisted state; never initialize on a read."""
    with closing(connect_database(path)) as connection, connection:
        connection.row_factory = sqlite3.Row
        connection.execute('BEGIN')
        return read_state(connection)


def read_state(connection):
    """Read inside the caller's transaction; caller sets sqlite3.Row factory."""
    settlement_id = _existing_settlement(connection)
    if settlement_id is None:
        return None
    settlement = dict(connection.execute('SELECT * FROM settlements WHERE settlement_id=?',
                      (settlement_id,)).fetchone())
    season = dict(connection.execute('SELECT * FROM seasons WHERE season_id=?',
                                    (settlement['season_id'],)).fetchone())
    config = load_config(season['config_version'])
    from game.expansion import overlay
    config, expansion = overlay(connection, season['season_id'], config)
    resources = connection.execute('SELECT * FROM settlement_resources WHERE settlement_id=?',
                                   (settlement_id,)).fetchone()
    buildings = [dict(row) for row in connection.execute(
        'SELECT * FROM buildings WHERE settlement_id=? ORDER BY building_id', (settlement_id,))]
    citizens = [dict(row) for row in connection.execute('''
        SELECT c.citizen_id,c.name,c.sex,c.level,c.xp,c.current_hp,c.morale,c.integrated,c.homeless_since,c.unemployed_since,
               COALESCE((SELECT min(h.joined_at) FROM citizen_settlement_history h
                   WHERE h.citizen_id=c.citizen_id AND h.settlement_id=c.settlement_id AND h.left_at IS NULL),c.created_at) AS joined_at,
               COALESCE(a.assignment_type,'unassigned') AS assignment,
               a.assignment_id,a.building_id,a.job_id,
               EXISTS(SELECT 1 FROM attack_citizens ac WHERE ac.citizen_id=c.citizen_id AND ac.role='attacker' AND ac.released_at IS NULL) AS away
        FROM citizens c LEFT JOIN citizen_assignments a
            ON a.citizen_id=c.citizen_id AND a.ended_at IS NULL
        WHERE c.settlement_id=? AND c.status='alive' ORDER BY c.citizen_id''', (settlement_id,))]
    jobs = [dict(row) for row in connection.execute(
        'SELECT * FROM settlement_jobs WHERE settlement_id=? ORDER BY job_id', (settlement_id,))]
    derelicts = [dict(row) for row in connection.execute('''SELECT d.*,s.derelict_type,s.origin_x,s.origin_y,s.rotation
        FROM settlement_derelicts d JOIN season_derelicts s USING(season_derelict_id)
        WHERE d.settlement_id=? ORDER BY settlement_derelict_id''', (settlement_id,))]
    allowed = config['buildings'] if season['config_version']=='prototype_v13' else {
        **load_config('prototype_v13')['buildings'], **(config['buildings'] if expansion else {})}
    storage_event=connection.execute("SELECT event_data FROM game_events WHERE settlement_id=? AND event_type='prototype_food_storage_lock' ORDER BY event_id DESC LIMIT 1",(settlement_id,)).fetchone()
    storage_lock=json.loads(storage_event[0]) if storage_event else {}
    if resources is None or not buildings or buildings[0]['building_type'] != 'town_hall' or any(
            b['building_type'] not in allowed or not 1 <= b['level'] <= allowed[b['building_type']]['max_level']
            for b in buildings) or sum(b['building_type'] == 'town_hall' for b in buildings) != 1:
        raise ValueError('This save is incomplete or belongs to a later prototype. No data was changed.')
    state = {'settlement': settlement, 'season': season, 'resources': dict(resources),
            'buildings': buildings, 'citizens': citizens, 'jobs': jobs, 'derelicts': derelicts,
            'storage_lock':storage_lock,'config': config,'expansion':expansion}
    from game.expeditions import decorate as decorate_expeditions
    decorate_expeditions(connection,state)
    state['reserved'] = {r['resource_type']: r['quantity'] for r in connection.execute('''SELECT resource_type,sum(quantity) AS quantity FROM resource_reservations WHERE settlement_id=? AND released_at IS NULL GROUP BY resource_type''', (settlement_id,))}
    state['policies'] = dict(connection.execute('SELECT * FROM settlement_policies WHERE settlement_id=?', (settlement_id,)).fetchone())
    needs_event = connection.execute("SELECT event_data FROM game_events WHERE settlement_id=? AND event_type='prototype_needs_clock' ORDER BY event_id DESC LIMIT 1", (settlement_id,)).fetchone()
    state['needs_clock'] = json.loads(needs_event[0]) if needs_event else None
    state['units'] = [dict(r) for r in connection.execute('SELECT * FROM military_units WHERE settlement_id=? ORDER BY unit_id', (settlement_id,))]
    state['inventory'] = [dict(r) for r in connection.execute('SELECT * FROM military_inventory WHERE settlement_id=? ORDER BY inventory_id', (settlement_id,))]
    state['repair_drone_orders']={}
    if 'maintenance' in config:
        for row in connection.execute("SELECT event_data FROM game_events WHERE settlement_id=? AND event_type='prototype_repair_drone_order' ORDER BY event_id",(settlement_id,)):
            data=json.loads(row[0]);state['repair_drone_orders'][str(data['unit_id'])]=data
    state['munition_reservations']=[dict(r) for r in connection.execute("SELECT i.building_id,am.quantity-am.consumed_quantity AS quantity FROM attack_munitions am JOIN attacks a USING(attack_id) JOIN military_inventory i USING(inventory_id) WHERE am.participant_settlement_id=? AND am.role='attacker' AND a.status='in_flight'",(settlement_id,))]
    if 'consequences' in config:
        row=connection.execute("SELECT event_data FROM game_events WHERE settlement_id=? AND event_type='citizen_consequences_clock' ORDER BY event_id DESC LIMIT 1",(settlement_id,)).fetchone()
        state['consequences_clock']=json.loads(row[0]) if row else {'enabled_at':settlement['simulation_processed_at'],'exposed':{},'deliberate':[],'day':settlement['simulation_processed_at']//86400,'seed':season['map_seed']}
    if expansion:
        from game.banking import debt,value
        from game.expansion import config as expansion_config
        rules=expansion_config()['settings']['Economy Diplomacy']
        ratio=debt(connection,settlement_id)/max(1,value(connection,state))
        threshold=rules['debt_morale_start']/100
        state['debt_morale_modifier']=rules['debt_morale_max']*min(1,max(0,(ratio-threshold)/(2*rules['loan_max_pct_settlement_value']/100-threshold)))
    if season['config_version'] in ('prototype_v6','prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
        event=connection.execute("SELECT event_data FROM game_events WHERE settlement_id=? AND event_type='prototype_recovery_clock' ORDER BY event_id DESC LIMIT 1",(settlement_id,)).fetchone()
        if not event:
            raise ValueError('The recovery clock is missing. No data was changed.')
        state['recovery_clock']=json.loads(event[0])
        from game.recovery import decorate
        decorate(state)
    if season['config_version'] in ('prototype_v7','prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
        event=connection.execute("SELECT event_data FROM game_events WHERE settlement_id=? AND event_type='prototype_xp_clock' ORDER BY event_id DESC LIMIT 1",(settlement_id,)).fetchone()
        if not event:raise ValueError('The XP clock is missing. No data was changed.')
        state['xp_clock']=json.loads(event[0])
    if season['config_version'] in ('prototype_v8','prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
        event=connection.execute("SELECT event_data FROM game_events WHERE settlement_id=? AND event_type='prototype_regen_clock' ORDER BY event_id DESC LIMIT 1",(settlement_id,)).fetchone()
        if not event:raise ValueError('The regeneration clock is missing.')
        state['regen_pending']=json.loads(event[0])['pending']
    return state


def seed_settlement(connection,account_id,season_id,name,config,now,x,y):
    hall=config['town_hall']
    settlement_id = connection.execute('''INSERT INTO settlements
        (season_id,account_id,settlement_name,town_hall_x,town_hall_y,created_at,
         protection_until,protection_type,status,simulation_processed_at,attacks_remaining)
        VALUES (?,?,?,?,?,?,?,'beginner','active',?,?)''',
        (season_id, account_id, name, x, y, now,
         now + config['beginner_protection_hours'] * 3600, now,
         config['starting_attacks'])).lastrowid
    building_id = connection.execute('''INSERT INTO buildings
        (settlement_id,building_type,level,origin_x,origin_y,current_hp,status,created_at,completed_at)
        VALUES (?,'town_hall',1,?,?,?,'active',?,?)''',
        (settlement_id, x, y, hall['hp'], now, now)).lastrowid
    resources = config['resources']
    connection.execute('''INSERT INTO settlement_resources
        (settlement_id,food,water,scrap,metal,electronics,credits,updated_at)
        VALUES (?,?,?,?,?,?,?,?)''', (settlement_id, resources['food'], resources['water'],
        resources['scrap'], resources['metal'], resources['electronics'], resources['credits'], now))
    connection.execute("INSERT INTO settlement_policies VALUES (?,'full','full',?)", (settlement_id, now))
    # Preserve the initial names where available; new arrivals must remain unique across captures.
    from game.population import unique_name
    names = [('Mara Vale', 'female'), ('Elias Reed', 'male'), ('Nora Flint', 'female'),
             ('Jonah Cross', 'male'), ('Ada Stone', 'female'), ('Silas Ward', 'male')]
    if config['starting_population'] != len(names):
        raise ValueError('Prototype citizen names must match configured starting population.')
    for index, (citizen_name, sex) in enumerate(names):
        citizen_name = unique_name(connection, settlement_id, citizen_name)
        citizen_id = connection.execute('''INSERT INTO citizens
            (settlement_id,original_settlement_id,name,sex,current_hp,morale,status,
             unemployed_since,created_at) VALUES (?,?,?,?,?,?,'alive',?,?)''',
            (settlement_id, settlement_id, citizen_name, sex, config['citizen_hp'],
             config['citizen_morale'], None if index == 0 else now, now)).lastrowid
        connection.execute('''INSERT INTO citizen_settlement_history
            (citizen_id,settlement_id,joined_at,arrival_reason) VALUES (?,?,?,'starting_citizen')''',
            (citizen_id, settlement_id, now))
        connection.execute('''INSERT INTO citizen_level_history
            (citizen_id,level,xp_total,reached_at) VALUES (?,1,0,?)''', (citizen_id, now))
        if index == 0:
            connection.execute('''INSERT INTO citizen_assignments
                (citizen_id,settlement_id,assignment_type,building_id,assigned_at)
                VALUES (?,?,'administrator',?,?)''', (citizen_id, settlement_id, building_id, now))
    # Record the initial transfer; financial gameplay is still inactive.
    credits = resources['credits']
    connection.execute('INSERT INTO season_bank VALUES (?,?,?) ON CONFLICT(season_id) DO UPDATE SET credits=credits-?,updated_at=?', (season_id, -credits, now,credits,now))
    for owner, amount in [(None, -credits), (settlement_id, credits)]:
        connection.execute('''INSERT INTO credit_transactions
            (season_id,settlement_id,transfer_ref,transaction_type,amount,balance_after,occurred_at)
            VALUES (?,?,?,'starting_credits',?,?,?)''',
            (season_id, owner, f'start:{settlement_id}', amount, connection.execute('SELECT credits FROM season_bank WHERE season_id=?',(season_id,)).fetchone()[0] if owner is None else amount, now))
    connection.execute('''INSERT INTO game_events
        (season_id,settlement_id,event_type,occurred_at,event_data)
        VALUES (?,?,'settlement_created',?,?)''', (season_id, settlement_id, now,
        json.dumps({'config_version': config['version'], 'prototype': True})))
    return settlement_id

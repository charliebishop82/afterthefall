"""Password hashes, persistent account sessions and shared-season enrollment."""
from contextlib import closing
import hashlib,hmac,secrets,re,sqlite3,time
from database.create_database import connect_database,create_database,SCHEMA_VERSION
from game.settlement import account_scope,seed_settlement,read_state,load_config
from pathlib import Path


def prepare(path):
    path=Path(path)
    if not path.exists():create_database(path)
    with closing(connect_database(path)) as c,c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute('PRAGMA user_version').fetchone()[0]!=SCHEMA_VERSION:raise ValueError('Unsupported account database schema.')
        tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'auth_sessions' not in tables and (c.execute('SELECT count(*) FROM accounts').fetchone()[0] or c.execute('SELECT count(*) FROM seasons').fetchone()[0]):
            raise ValueError('Use a separate account database; your local prototype save cannot be used here.')
        c.execute('''CREATE TABLE IF NOT EXISTS auth_sessions(token_hash TEXT PRIMARY KEY,account_id INTEGER REFERENCES accounts(account_id),csrf TEXT NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL) STRICT''')
        c.execute('CREATE TABLE IF NOT EXISTS auth_failures(username TEXT PRIMARY KEY,failures INTEGER NOT NULL,blocked_until INTEGER NOT NULL) STRICT')
        # State snapshots repeatedly seek the latest clock by event type. Keep
        # this lookup bounded as an existing playtest's event history grows.
        c.execute('CREATE INDEX IF NOT EXISTS events_latest ON game_events(settlement_id,event_type,event_id)')
        from game.market import prepare as prepare_market
        prepare_market(c,int(time.time()))
        from game.expeditions import prepare as prepare_expeditions
        prepare_expeditions(c)
        from game.offline import prepare as prepare_offline
        prepare_offline(c)


def password_hash(password):
    salt=secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),bytes.fromhex(salt),600000).hex()
    return f'pbkdf2_sha256$600000${salt}${digest}'


def verify(password,stored):
    try:
        name,iterations,salt,digest=stored.split('$')
        if name!='pbkdf2_sha256' or int(iterations)!=600000:return False
        actual=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),bytes.fromhex(salt),int(iterations)).hex()
        return hmac.compare_digest(actual,digest)
    except (ValueError,TypeError):return False


def register_in_transaction(c,username,password,now):
    username=username.strip().lower()
    if not re.fullmatch('[a-z][a-z0-9_]{2,23}',username):raise ValueError('Use 3–24 letters, numbers or underscores, starting with a letter.')
    if not 12<=len(password)<=128:raise ValueError('Use a password of 12–128 characters.')
    hashed=password_hash(password)
    try:return c.execute('INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES (?,?,?,?)',(username,hashed,username,now)).lastrowid
    except sqlite3.IntegrityError:raise ValueError('That username is already taken.') from None


def register(path,username,password,now):
    with closing(connect_database(path)) as c,c:
        return register_in_transaction(c,username,password,now)


def authenticate(path,username,password,now):
    username=username.strip().lower()
    with closing(connect_database(path)) as c,c:
        c.execute('BEGIN IMMEDIATE')
        failure=c.execute('SELECT blocked_until FROM auth_failures WHERE username=?',(username,)).fetchone()
        if failure and failure[0]>now:return None
        row=c.execute('SELECT account_id,password_hash,is_active FROM accounts WHERE username=?',(username,)).fetchone()
        valid=verify(password,row[1] if row else 'pbkdf2_sha256$600000$'+'00'*16+'$'+'00'*32)
        if not row or not valid or not row[2]:
            c.execute('INSERT INTO auth_failures VALUES (?,1,0) ON CONFLICT(username) DO UPDATE SET failures=failures+1',(username,))
            if c.execute('SELECT failures FROM auth_failures WHERE username=?',(username,)).fetchone()[0]>=5:c.execute('UPDATE auth_failures SET blocked_until=?,failures=0 WHERE username=?',(now+60,username))
            return None
        c.execute('DELETE FROM auth_failures WHERE username=?',(username,));return row[0]


def new_session(path,account_id,now,old_token=None):
    token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(32)
    with closing(connect_database(path)) as c,c:
        if old_token:c.execute('DELETE FROM auth_sessions WHERE token_hash=?',(hashlib.sha256(old_token.encode()).hexdigest(),))
        c.execute('DELETE FROM auth_sessions WHERE expires_at<=?',(now,))
        c.execute('INSERT INTO auth_sessions VALUES (?,?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),account_id,csrf,now,now+86400))
    return token,{'account_id':account_id,'csrf':csrf,'expires_at':now+86400}


def session(path,token,now):
    if not token or len(token)>128:return None
    with closing(connect_database(path)) as c:
        c.row_factory=sqlite3.Row
        row=c.execute('SELECT s.*,a.username,a.is_active FROM auth_sessions s LEFT JOIN accounts a USING(account_id) WHERE token_hash=? AND expires_at>?',(hashlib.sha256(token.encode()).hexdigest(),now)).fetchone()
        return dict(row) if row and (row['account_id'] is None or row['is_active']) else None


def join(path,account_id,name,now):
    with closing(connect_database(path)) as c,c,account_scope(account_id):
        c.row_factory=sqlite3.Row;c.execute('BEGIN IMMEDIATE')
        return join_in_transaction(c,account_id,name,now)


def join_in_transaction(c,account_id,name,now):
    """Join using the caller's transaction and account scope, also used by shared launch."""
    name=name.strip()
    if not 1<=len(name)<=40 or any(ord(ch)<32 for ch in name):raise ValueError('Use a settlement name of 1–40 characters without control characters.')
    if not c.execute('SELECT 1 FROM accounts WHERE account_id=? AND is_active=1',(account_id,)).fetchone():raise ValueError('This account is unavailable.')
    if read_state(c):return read_state(c)['settlement']['settlement_id']
    config=load_config('prototype_v1');season=c.execute("SELECT * FROM seasons ORDER BY season_id DESC LIMIT 1").fetchone()
    if season and (season['status'] != 'active' or now>=season['finalization_at'] or now>=season['ends_at'] or now<season['started_at']):raise ValueError('Joining this season is closed.')
    if not season:
        end=now+config['season_days']*86400
        sid=c.execute("INSERT INTO seasons(name,status,scheduled_start_at,started_at,finalization_at,ends_at,created_at,config_version,map_seed) VALUES ('Account prototype','active',?,?,?,?,?,'prototype_v1',?)",(now,now,end-10800,end,now,secrets.token_hex(16))).lastrowid
    else:sid=season['season_id'];c.execute("UPDATE seasons SET config_version='prototype_v1' WHERE season_id=?",(sid,))
    hall=config['town_hall'];x=(config['map_width']-hall['width'])//2;y=(config['map_height']-hall['height'])//2
    try:settlement_id=seed_settlement(c,account_id,sid,name,config,now,x,y)
    except sqlite3.IntegrityError:raise ValueError('That settlement name is already taken.') from None
    from game.repairs import enable
    enable(c,read_state(c),now)
    if season and season['config_version'] in ('prototype_v9','prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
        from game.manufacturing import enable as enable_military
        enable_military(c,read_state(c),now)
    if season and season['config_version'] in ('prototype_v10','prototype_v11','prototype_v12','prototype_v13'):
        from game.support import enable as enable_support
        enable_support(c,read_state(c),now)
    if season and season['config_version'] in ('prototype_v11','prototype_v12','prototype_v13'):
        from game.maintenance import enable as enable_maintenance
        enable_maintenance(c,read_state(c),now)
    if season and season['config_version'] in ('prototype_v12','prototype_v13'):
        from game.structural import enable as enable_structural
        enable_structural(c,read_state(c),now)
    if season and season['config_version']=='prototype_v13':
        from game.consequences import enable as enable_consequences
        enable_consequences(c,read_state(c),now)
    from game.expansion import enabled as expansion_enabled, fund
    if expansion_enabled(c,sid):fund(c,read_state(c),now)
    return settlement_id

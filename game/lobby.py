"""Shared launch, normal late joins, and paused-season reservations."""
from contextlib import closing
from pathlib import Path
import sqlite3

from database.create_database import connect_database
from game import accounts, admin
from game.settlement import account_scope, read_state


def prepare(path):
    path = Path(path)
    if path.exists():
        with closing(connect_database(path)) as c:
            tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'playtest_control' not in tables and (
                ('accounts' in tables and c.execute('SELECT count(*) FROM accounts').fetchone()[0]) or
                ('seasons' in tables and c.execute('SELECT count(*) FROM seasons').fetchone()[0])
            ):
                raise ValueError('Choose a fresh playtest database. Existing accounts and saves are preserved.')
    accounts.prepare(path)
    with closing(connect_database(path)) as c, c:
        c.execute('''CREATE TABLE IF NOT EXISTS playtest_control(
            singleton INTEGER PRIMARY KEY CHECK(singleton=1),
            status TEXT NOT NULL CHECK(status IN ('waiting','started')),
            started_at INTEGER,started_by INTEGER REFERENCES accounts(account_id)) STRICT''')
        c.execute("INSERT OR IGNORE INTO playtest_control(singleton,status) VALUES (1,'waiting')")
        c.execute('''CREATE TABLE IF NOT EXISTS playtest_members(
            account_id INTEGER PRIMARY KEY REFERENCES accounts(account_id),
            settlement_name TEXT NOT NULL UNIQUE CHECK(length(trim(settlement_name)) BETWEEN 1 AND 40),
            enrolled_at INTEGER NOT NULL) STRICT''')


def status(path):
    with closing(connect_database(path)) as c:
        c.row_factory = sqlite3.Row
        control = dict(c.execute('SELECT * FROM playtest_control WHERE singleton=1').fetchone())
        control['members'] = [dict(r) for r in c.execute('''SELECT m.account_id,m.settlement_name,a.is_active
            FROM playtest_members m JOIN accounts a USING(account_id) ORDER BY m.account_id''')]
        return control


def enrollment_open(season, now):
    if not season: return False
    at=season['paused_at'] if season['status']=='paused' else now
    return (season['status'] in ('active','paused') and at is not None and
            at>=season['started_at'] and at<season['finalization_at'] and at<season['ends_at'])


def join_member(c, member, now):
    """Same normal account seed; no catch-up grants or elapsed pre-join time."""
    from game import needs
    from game.simulation import _event
    with account_scope(member['account_id']):
        sid=accounts.join_in_transaction(c,member['account_id'],member['settlement_name'],now)
        state=read_state(c)
        if not needs.enabled(state):
            needs.record(c,state,now,{'since':{'food':None,'water':None},'pending':{}})
            state=read_state(c)
        _event(c,state,'playtest_late_join',now,{'joined_at':now,'normal_start':True})
        return sid


def activate_reserved(c, now, season_id):
    """Called inside administrator resume, atomically with that resume."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='playtest_members'").fetchone(): return
    season=c.execute('SELECT * FROM seasons ORDER BY season_id DESC LIMIT 1').fetchone()
    if not season or season['season_id']!=season_id or season['status']!='active' or not enrollment_open(season,now): return
    members=c.execute("""SELECT m.* FROM playtest_members m JOIN accounts a USING(account_id)
        WHERE a.is_active=1 AND NOT EXISTS(SELECT 1 FROM settlements s
          WHERE s.account_id=m.account_id AND s.season_id=?) ORDER BY m.account_id""",(season_id,)).fetchall()
    for member in members: join_member(c,member,now)


def enroll(path, actor, name, now):
    name = name.strip()
    if not 1 <= len(name) <= 40 or any(ord(ch)<32 for ch in name):
        raise ValueError('Use a settlement name of 1–40 characters without control characters.')
    with closing(connect_database(path)) as c, c:
        c.row_factory=sqlite3.Row
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM accounts WHERE account_id=? AND is_active=1', (actor,)).fetchone():
            raise PermissionError('Log in first.')
        started=c.execute('SELECT status FROM playtest_control WHERE singleton=1').fetchone()[0]=='started'
        season=c.execute('SELECT * FROM seasons ORDER BY season_id DESC LIMIT 1').fetchone()
        if started:
            if c.execute('SELECT 1 FROM settlements WHERE account_id=? AND season_id=?',(actor,season['season_id'])).fetchone():
                raise ValueError('You already have a settlement in this season.')
            if not enrollment_open(season,now):
                raise ValueError('Enrollment closes during finalization and after the season ends.')
        try:
            c.execute('''INSERT INTO playtest_members VALUES (?,?,?) ON CONFLICT(account_id)
                DO UPDATE SET settlement_name=excluded.settlement_name,enrolled_at=excluded.enrolled_at''', (actor, name, now))
        except sqlite3.IntegrityError:
            raise ValueError('That settlement name is already reserved.') from None
        if started and season['status']=='active':
            member=c.execute('SELECT * FROM playtest_members WHERE account_id=?',(actor,)).fetchone()
            return join_member(c,member,now)
        return None


def start(path, actor, now, reason):
    """Seed every eligible settlement in one transaction, using exactly the same time."""
    from game import communication, expansion, needs
    with closing(connect_database(path)) as c, c:
        c.row_factory = sqlite3.Row
        c.execute('BEGIN IMMEDIATE')
        admin.require(c, actor)
        reason = communication.text(reason, 200)
        if c.execute('SELECT status FROM playtest_control WHERE singleton=1').fetchone()[0] != 'waiting':
            raise ValueError('The playtest has already started.')
        members = c.execute('''SELECT m.* FROM playtest_members m JOIN accounts a USING(account_id)
            WHERE a.is_active=1 ORDER BY m.account_id''').fetchall()
        if not members:
            raise ValueError('At least one active player must reserve a settlement first.')
        for member in members:
            with account_scope(member['account_id']):
                accounts.join_in_transaction(c, member['account_id'], member['settlement_name'], now)
        # Enable the already-built gameplay catalog equally, without replaying any elapsed time.
        with account_scope(members[0]['account_id']):
            expansion.enable(c, read_state(c), now)
        for member in members:
            with account_scope(member['account_id']):
                state = read_state(c)
                if not needs.enabled(state):
                    needs.record(c, state, now, {'since':{'food':None,'water':None},'pending':{}})
        c.execute("UPDATE playtest_control SET status='started',started_at=?,started_by=? WHERE singleton=1", (now, actor))
        season = c.execute('SELECT season_id FROM seasons ORDER BY season_id DESC LIMIT 1').fetchone()[0]
        admin.audit(c, actor, 'playtest_start', 'season', season, now, reason,
                    {'status':'waiting'}, {'status':'started','players':len(members),'started_at':now}, season)
        return len(members)

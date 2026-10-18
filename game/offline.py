"""48-hour local simulation allowance between a player's own active requests.

Other players and admin inspection never renew the allowance. Shared combat,
Bank obligations and real-world deadlines do not receive extra protection.
"""
from contextlib import closing
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path

from database.create_database import connect_database


@lru_cache(maxsize=1)
def settings():
    value=json.loads((Path(__file__).resolve().parents[1]/'config/offline.json').read_text(encoding='utf-8'))
    if type(value.get('enabled')) is not bool or type(value.get('max_hours')) is not int or value['max_hours']<=0:
        raise ValueError('Offline settings need enabled and a positive whole max_hours.')
    return value


def prepare(c):
    c.execute('''CREATE TABLE IF NOT EXISTS settlement_activity(
        settlement_id INTEGER PRIMARY KEY REFERENCES settlements(settlement_id),
        last_active_at INTEGER NOT NULL,
        skipped_seconds INTEGER NOT NULL DEFAULT 0,
        last_cap_seconds INTEGER NOT NULL DEFAULT 0,
        last_capped_at INTEGER) STRICT''')
    # Existing saves have no reliable historical login clock. Preserve all
    # earned progress and start the policy from each saved simulation clock.
    c.execute('''INSERT OR IGNORE INTO settlement_activity(settlement_id,last_active_at)
        SELECT settlement_id,simulation_processed_at FROM settlements''')


def exists(c):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='settlement_activity'").fetchone() is not None


def cutoff(c,state):
    from game.settlement import CURRENT_ACCOUNT
    if not state or CURRENT_ACCOUNT.get() is None or state['season']['config_version']!='prototype_v13' or not settings()['enabled'] or not exists(c):
        return None
    row=c.execute('SELECT last_active_at FROM settlement_activity WHERE settlement_id=?',
                  (state['settlement']['settlement_id'],)).fetchone()
    active=row[0] if row else state['settlement']['simulation_processed_at']
    return active+settings()['max_hours']*3600


def ensure_activity(c,state):
    if exists(c):
        c.execute('INSERT OR IGNORE INTO settlement_activity(settlement_id,last_active_at) VALUES (?,?)',
                  (state['settlement']['settlement_id'],state['settlement']['simulation_processed_at']))


def touch(path,account_id,now):
    """Only successful own gameplay views/actions renew the allowance."""
    with closing(connect_database(path)) as c,c:
        if not exists(c):return
        row=c.execute('SELECT settlement_id FROM settlements WHERE account_id=? ORDER BY season_id DESC LIMIT 1',
                      (account_id,)).fetchone()
        if not row:return
        c.execute('''INSERT INTO settlement_activity(settlement_id,last_active_at)
            VALUES (?,?)
            ON CONFLICT(settlement_id) DO UPDATE SET
                last_active_at=max(settlement_activity.last_active_at,excluded.last_active_at),
                skipped_seconds=CASE WHEN excluded.last_active_at>settlement_activity.last_active_at THEN 0 ELSE settlement_activity.skipped_seconds END''',
                  (row[0],now))


def shift_activity(c,state,seconds):
    """Administrative pauses preserve the remaining offline allowance too."""
    if seconds and exists(c):
        c.execute('UPDATE settlement_activity SET last_active_at=last_active_at+? WHERE settlement_id=?',
                  (seconds,state['settlement']['settlement_id']))


def skip(c,state,now):
    """Freeze local clocks over excess inactivity; leave shared deadlines intact."""
    start=state['settlement']['simulation_processed_at'];seconds=now-start
    if seconds<=0:return
    sid=state['settlement']['settlement_id']
    ensure_activity(c,state)
    from game.expeditions import shift_clock
    shift_clock(c,state,seconds)
    if state.get('recovery_clock'):
        clock=deepcopy(state['recovery_clock']);clock['anchor']+=seconds
        from game.recovery import record_clock
        record_clock(c,state,now,clock)
    if state.get('needs_clock'):
        clock=deepcopy(state['needs_clock'])
        clock['since']={r:value+seconds if value is not None else None for r,value in clock['since'].items()}
        from game.needs import record
        record(c,state,now,clock)
    if state.get('consequences_clock'):
        clock=deepcopy(state['consequences_clock']);clock['enabled_at']+=seconds;clock['day']=now//86400
        from game.consequences import record
        record(c,state,now,clock)
    c.execute('''UPDATE citizens SET unemployed_since=unemployed_since+?,homeless_since=homeless_since+?
        WHERE settlement_id=? AND status='alive' ''',(seconds,seconds,sid))
    c.execute("UPDATE settlement_jobs SET last_processed_at=last_processed_at+? WHERE settlement_id=? AND status IN ('queued','active','paused')",
              (seconds,sid))
    c.execute('UPDATE settlements SET simulation_processed_at=? WHERE settlement_id=?',(now,sid))
    # Capture integration and its desertion roll are local citizen progress.
    pending=[citizen['citizen_id'] for citizen in state['citizens'] if not citizen['integrated']]
    from game.simulation import _event
    if pending and state.get('expansion'):
        _event(c,state,'captured_integration_deferred',now,{'until':(now//86400+1)*86400,'citizens':pending})
    from game.settlement import read_state
    current=read_state(c)
    if state.get('expansion'):
        from game import banking
        banking.accrue(c,current,now)
        banking.liquidate(c,read_state(c),now)
    from game.trading import expire
    expire(c,read_state(c),now)
    # Attack allowance/floor rollover remains shared-time behavior. Births and
    # ordinary citizen desertion are paused by the shifted consequences clock.
    from game.combat import daily
    daily(c,read_state(c),now)
    c.execute('''UPDATE settlement_activity SET skipped_seconds=skipped_seconds+?,
        last_cap_seconds=skipped_seconds+?,last_capped_at=? WHERE settlement_id=?''',
              (seconds,seconds,now,sid))
    _event(c,state,'offline_time_capped',now,{'from':start,'until':now,'skipped_seconds':seconds,
                                          'max_hours':settings()['max_hours']})


def notice(path,state):
    with closing(connect_database(path)) as c:
        if not exists(c):return ''
        row=c.execute('SELECT last_cap_seconds FROM settlement_activity WHERE settlement_id=?',
                      (state['settlement']['settlement_id'],)).fetchone()
    if not row or not row[0]:return ''
    return ('<p class="attention-warning" role="status">Offline simulation is capped at '
            f'{settings()["max_hours"]} hours. During your last capped absence, {row[0]/3600:.1f} '
            'additional hours of local activity were paused. Shared deadlines and Bank obligations continued.</p>')

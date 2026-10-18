"""Resumable catch-up for HTTP and the background settlement coordinator.

The wall-time budget is soft: a simulation step (including dependent combat)
always finishes atomically. Callers share the player server gate and clock.
"""
from contextlib import closing
import sqlite3
import time

from database.create_database import connect_database
from game.settlement import account_scope, read_state

LIVE_WINDOW = 120
BATCH_SECONDS = 0.6
HORIZON = 3600


def _pending(connection, account_id, now, shared=False):
    season = connection.execute('''SELECT se.* FROM seasons se JOIN settlements s USING(season_id)
        WHERE s.account_id=? ORDER BY s.season_id DESC LIMIT 1''', (account_id,)).fetchone()
    if not season or season['status'] not in ('active', 'finalizing'):
        return [], now
    goal = min(now, season['ends_at'])
    # Unrelated rankings use saved snapshots. Shared combat/finalization still
    # require synchronized participants. Bank actions explicitly request shared
    # catch-up before executing their existing authoritative refresh.
    shared = shared or goal >= season['ends_at'] or bool(connection.execute(
        "SELECT 1 FROM attacks WHERE season_id=? AND status='in_flight' AND resolves_at<=? LIMIT 1",
        (season['season_id'],goal)).fetchone())
    rows = connection.execute('''SELECT s.* FROM settlements s JOIN accounts a USING(account_id)
        WHERE s.season_id=? AND s.status='active' AND a.is_active=1
        ORDER BY s.simulation_processed_at,s.settlement_id''', (season['season_id'],)).fetchall()
    from game.admin_controls import frozen
    rows = [r for r in rows if (r['account_id'] == account_id or shared)
            and not frozen(connection, {'season': season, 'settlement': r})
            and r['simulation_processed_at'] < goal]
    return rows, goal


def _report(rows, goal, steps=0):
    remaining = sum(goal-r['simulation_processed_at'] for r in rows)
    oldest = min((r['simulation_processed_at'] for r in rows), default=goal)
    return {'status': 'catching_up' if goal-oldest > LIVE_WINDOW else 'ready',
            'remaining_seconds': remaining, 'oldest_clock': oldest,
            'target_clock': goal, 'settlements_remaining': len(rows), 'batches_completed': steps}


def status(path, account_id, now, shared=False):
    with closing(connect_database(path)) as c:
        c.row_factory = sqlite3.Row
        return _report(*_pending(c, account_id, now, shared))


def step(path, account_id, now, shared=False):
    """Commit one bounded batch; another request can resume after interruption."""
    from game.simulation import _advance
    from game.calculations import scope
    started = time.perf_counter()
    with closing(connect_database(path)) as c, c:
        c.row_factory = sqlite3.Row
        c.execute('BEGIN IMMEDIATE')
        rows, goal = _pending(c, account_id, now, shared)
        if not rows:
            # A background coordinator must also finalize a season after its
            # participants reach the end, without waiting for a player page.
            with account_scope(account_id):
                current=read_state(c)
                if (current and current['season']['status'] in ('active','finalizing')
                        and now>=current['season']['ends_at']):
                    _advance(c,current,now,deadline=started+BATCH_SECONDS,max_intervals=32)
            return _report(rows, goal)
        # Quiet periods can cover more game time without increasing the soft
        # processing budget. Near shared events keep dependency catch-up short.
        player = rows[0]
        target = min(goal, player['simulation_processed_at'] + HORIZON)
        from game.offline import cutoff
        with account_scope(player['account_id']):
            current=read_state(c)
            offline_until=cutoff(c,current)
        if offline_until is not None and player['simulation_processed_at']>=offline_until:
            target=goal
        attack_at = c.execute("""SELECT min(resolves_at) FROM attacks
            WHERE season_id=? AND status='in_flight' AND resolves_at>?
            AND resolves_at<=?""", (player['season_id'],
                player['simulation_processed_at'],target)).fetchone()[0]
        if attack_at is not None:
            target = min(target,attack_at,player['simulation_processed_at']+300)
        end = c.execute('SELECT ends_at FROM seasons WHERE season_id=?',
                        (player['season_id'],)).fetchone()[0]
        if target >= end and player['simulation_processed_at'] < end-300:
            target = end-300
        with account_scope(player['account_id']), scope() as metrics:
            from game.catchup_diagnostics import bulk_blockers
            blockers=bulk_blockers(current)
            _advance(c, current, target,
                     deadline=started+BATCH_SECONDS, max_intervals=32)
        rows, goal = _pending(c, account_id, now, shared)
        result = _report(rows, goal, 1)
        result['step_limits']=dict(metrics['step_limits'])
        result['bulk_blockers']=blockers
        result['processed_account_id']=player['account_id']
        result['processed_settlement_id']=player['settlement_id']
        result['duration_ms'] = round((time.perf_counter()-started)*1000, 3)
        result['calculations'] = {key:round(metrics[key],3) for key in
                                  ('utility_calls','utility_hits','utility_compute_ms','state_reads','state_read_ms',
                                   'simulation_intervals','long_intervals','long_interval_seconds','rule_snapshot_hits')}
        return result

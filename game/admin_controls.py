"""Audited operational controls; game balance and original records stay unchanged."""
import copy
import json
import math

from game.settlement import account_scope, read_state

CORRECTIONS = ('correct_resource', 'correct_citizen_hp', 'correct_citizen_morale',
               'correct_building_hp', 'correct_attacks', 'correct_debt')


def ensure(c):
    # Operational pause metadata, like the lobby tables, is additive to V1.
    c.execute('''CREATE TABLE IF NOT EXISTS admin_freezes (
        settlement_id INTEGER PRIMARY KEY REFERENCES settlements(settlement_id),
        started_at INTEGER NOT NULL, previous_status TEXT NOT NULL,
        previous_suspended_at INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS admin_timer_freezes (
        kind TEXT NOT NULL CHECK(kind IN ('trade','treaty','attack')),
        target_id INTEGER NOT NULL, started_at INTEGER NOT NULL,
        PRIMARY KEY(kind,target_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS admin_treaty_offsets (
        treaty_id INTEGER PRIMARY KEY REFERENCES treaties(treaty_id),
        accepted_seconds INTEGER NOT NULL CHECK(accepted_seconds>=0),
        cancelled_seconds INTEGER NOT NULL CHECK(cancelled_seconds>=0))''')


def table_exists(c, name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def frozen(c, state):
    if not state:
        return False
    if state['season']['status'] == 'paused':
        return True
    return table_exists(c, 'admin_freezes') and c.execute(
        'SELECT 1 FROM admin_freezes WHERE settlement_id=?',
        (state['settlement']['settlement_id'],)).fetchone() is not None


def timer_frozen(c, kind, identity):
    return table_exists(c, 'admin_timer_freezes') and c.execute(
        'SELECT 1 FROM admin_timer_freezes WHERE kind=? AND target_id=?', (kind, identity)).fetchone() is not None


def timer_now(c, kind, identity, now):
    if table_exists(c, 'admin_timer_freezes'):
        row = c.execute('SELECT started_at FROM admin_timer_freezes WHERE kind=? AND target_id=?', (kind, identity)).fetchone()
        if row:
            return min(now, row[0])
    return now


def treaty_offset(c, identity, field='accepted_at'):
    if table_exists(c, 'admin_treaty_offsets'):
        column = 'accepted_seconds' if field == 'accepted_at' else 'cancelled_seconds'
        row = c.execute(f'SELECT {column} FROM admin_treaty_offsets WHERE treaty_id=?', (identity,)).fetchone()
        if row:
            return row[0]
    return 0


def require_running(c, state):
    if not state:
        return
    personal = table_exists(c, 'admin_freezes') and c.execute('SELECT 1 FROM admin_freezes WHERE settlement_id=?', (state['settlement']['settlement_id'],)).fetchone()
    pause = c.execute("SELECT action_type FROM admin_actions WHERE target_type='season' AND target_id=? AND action_type IN ('pause_season','resume_season') ORDER BY admin_action_id DESC LIMIT 1", (state['season']['season_id'],)).fetchone()
    if personal or (state['season']['status'] == 'paused' and pause and pause[0] == 'pause_season'):
        raise ValueError('Gameplay is frozen by an administrator. Wait for reactivation or season resume.')


def shift_player(c, state, seconds, now):
    """Preserve partially completed work and damage, rather than replaying downtime."""
    from game.recovery import shift_clock
    from game.simulation import _event
    shift_clock(c, state, seconds, now)
    sid = state['settlement']['settlement_id']
    c.execute('''UPDATE settlements SET simulation_processed_at=simulation_processed_at+?,
        protection_until=protection_until+?,last_rollover_at=? WHERE settlement_id=?''',
        (seconds, seconds, now//86400*86400, sid))
    c.execute('''UPDATE citizens SET unemployed_since=unemployed_since+?,
        homeless_since=homeless_since+? WHERE settlement_id=? AND status='alive' ''', (seconds, seconds, sid))
    c.execute("UPDATE settlement_jobs SET last_processed_at=last_processed_at+? WHERE settlement_id=? AND status IN ('queued','active','paused')", (seconds, sid))
    if state.get('needs_clock'):
        from game.needs import record
        clock = copy.deepcopy(state['needs_clock'])
        clock['since'] = {r: value+seconds if value is not None else None for r, value in clock['since'].items()}
        record(c, state, now, clock)
    _event(c, state, 'admin_clock_shift', now, {'seconds': seconds})


def hold_timers(c, season, now, sid=None):
    """One hold per shared timer avoids double shifts during overlapping freezes."""
    for kind, table, key, status, parties in (
        ('trade', 'trade_proposals', 'trade_id', "status='pending'", ('proposer_settlement_id', 'recipient_settlement_id')),
        ('treaty', 'treaties', 'treaty_id', "status IN ('proposed','active','cancelled')", ('settlement_a_id', 'settlement_b_id')),
        ('attack', 'attacks', 'attack_id', "status='in_flight'", ('attacker_settlement_id', 'defender_settlement_id')),
    ):
        query = f'SELECT {key} FROM {table} WHERE season_id=? AND {status}'
        args = [season]
        if sid is not None:
            query += f' AND ({parties[0]}=? OR {parties[1]}=?)'
            args += [sid, sid]
        for row in c.execute(query, args).fetchall():
            c.execute('INSERT OR IGNORE INTO admin_timer_freezes VALUES (?,?,?)', (kind, row[0], now))


def release_timers(c, now):
    for hold in c.execute('SELECT * FROM admin_timer_freezes').fetchall():
        kind = hold['kind']
        table, key, parties, columns = {
            'trade': ('trade_proposals', 'trade_id', ('proposer_settlement_id', 'recipient_settlement_id'), ('expires_at',)),
            'treaty': ('treaties', 'treaty_id', ('settlement_a_id', 'settlement_b_id'), ('effective_at', 'cooldown_until', 'expires_at')),
            'attack': ('attacks', 'attack_id', ('attacker_settlement_id', 'defender_settlement_id'), ('resolves_at',)),
        }[kind]
        row = c.execute(f'SELECT * FROM {table} WHERE {key}=?', (hold['target_id'],)).fetchone()
        live = row and row['status'] in {'trade': ('pending',), 'treaty': ('proposed','active','cancelled'), 'attack': ('in_flight',)}[kind]
        if live:
            paused = c.execute("SELECT 1 FROM seasons WHERE season_id=? AND status='paused'", (row['season_id'],)).fetchone()
            personal = c.execute('SELECT 1 FROM admin_freezes WHERE settlement_id IN (?,?)', (row[parties[0]], row[parties[1]])).fetchone()
            if paused or personal:
                continue
            seconds = now - hold['started_at']
            if seconds < 0:
                raise ValueError('The clock is earlier than the pause.')
            assignments = ','.join(f'{name}={name}+?' for name in columns)
            c.execute(f'UPDATE {table} SET {assignments} WHERE {key}=?', [seconds]*len(columns)+[row[key]])
            if kind == 'treaty':
                c.execute('''INSERT INTO admin_treaty_offsets VALUES (?,?,?) ON CONFLICT(treaty_id)
                    DO UPDATE SET accepted_seconds=accepted_seconds+excluded.accepted_seconds,
                    cancelled_seconds=cancelled_seconds+excluded.cancelled_seconds''',
                    (row[key], seconds if row['accepted_at'] is not None else 0,
                     seconds if row['cancelled_at'] is not None else 0))
        c.execute('DELETE FROM admin_timer_freezes WHERE kind=? AND target_id=?', (kind, hold['target_id']))


def suspend(c, account, now):
    from game.simulation import _advance, _event
    snapshots = []
    for row in c.execute("SELECT * FROM settlements WHERE account_id=? AND status IN ('active','suspended')", (account,)).fetchall():
        with account_scope(account):
            state = read_state(c)
            if state['settlement']['settlement_id'] != row['settlement_id']:
                raise ValueError('Only the current settlement can be suspended.')
            _advance(c, state, now)
            state = read_state(c)
            if state['settlement']['status'] == 'archived':
                continue
            start = state['season']['paused_at'] if state['season']['status'] == 'paused' else now
            if start < state['settlement']['simulation_processed_at']:
                raise ValueError('The clock is earlier than the saved state.')
            sid = row['settlement_id']
            c.execute('INSERT INTO admin_freezes VALUES (?,?,?,?)', (sid, start, state['settlement']['status'], state['settlement']['suspended_at']))
            c.execute("UPDATE settlements SET status='suspended',suspended_at=? WHERE settlement_id=?", (start, sid))
            hold_timers(c, row['season_id'], start, sid)
            # Existing recall rule, applied immediately so protection is effective now.
            from game.combat import cancel
            raids = c.execute("SELECT * FROM attacks WHERE status='in_flight' AND (attacker_settlement_id=? OR defender_settlement_id=?)", (sid, sid)).fetchall()
            for raid in raids:
                cancel(c, raid, start, 'Administrator suspended a participant.')
            _event(c, state, 'settlement_suspended', start, {'account_id': account})
            snapshots.append({'settlement_id': sid, 'previous_status': state['settlement']['status'], 'recalled_attacks': [r['attack_id'] for r in raids]})
    return snapshots


def reactivate(c, account, now):
    from game.simulation import _event
    shifted = []
    for hold in c.execute('SELECT f.* FROM admin_freezes f JOIN settlements s USING(settlement_id) WHERE s.account_id=?', (account,)).fetchall():
        with account_scope(account):
            state = read_state(c)
            if state['settlement']['status'] == 'archived' or state['season']['status'] == 'finished':
                c.execute('DELETE FROM admin_freezes WHERE settlement_id=?', (hold['settlement_id'],))
                shifted.append({'settlement_id': hold['settlement_id'], 'archived_progress_preserved': True})
                continue
            end = state['season']['paused_at'] if state['season']['status'] == 'paused' else min(now, state['season']['ends_at'])
            seconds = end - hold['started_at']
            if seconds < 0:
                raise ValueError('The clock is earlier than the suspension.')
            if hold['previous_status'] == 'active':
                shift_player(c, state, seconds, end)
            c.execute('UPDATE settlements SET status=?,suspended_at=? WHERE settlement_id=?',
                      (hold['previous_status'], hold['previous_suspended_at'], hold['settlement_id']))
            c.execute('DELETE FROM admin_freezes WHERE settlement_id=?', (hold['settlement_id'],))
            _event(c, state, 'settlement_resumed', end, {'account_id': account, 'seconds': seconds})
            # Preserve an earlier supply pause marker, so normal trade recovery still works.
            if hold['previous_status'] == 'suspended':
                _event(c, state, 'prototype_supply_pause', hold['previous_suspended_at'], state['resources'])
            shifted.append({'settlement_id': hold['settlement_id'], 'seconds': seconds})
    release_timers(c, now)
    return shifted


def season_control(c, actor, action, target, now, reason):
    from game.admin import audit
    from game.simulation import _advance
    season = c.execute('SELECT * FROM seasons WHERE season_id=?', (target,)).fetchone()
    if not season:
        raise ValueError('Choose an existing season.')
    before = dict(season)
    players = c.execute('SELECT account_id,settlement_id FROM settlements WHERE season_id=?', (target,)).fetchall()
    if action == 'pause_season':
        if season['status'] not in ('active', 'finalizing') or now >= season['ends_at']:
            raise ValueError('Only a running season can be paused before its end.')
        for player in players:
            with account_scope(player['account_id']):
                state = read_state(c)
                if now < state['settlement']['simulation_processed_at']:
                    raise ValueError('The clock is earlier than saved progress.')
                _advance(c, state, now)
        c.execute("UPDATE seasons SET status='paused',paused_at=? WHERE season_id=?", (now, target))
        hold_timers(c, target, now)
    else:
        pause = c.execute("SELECT action_type,before_values,occurred_at FROM admin_actions WHERE action_type IN ('pause_season','resume_season') AND target_type='season' AND target_id=? ORDER BY admin_action_id DESC LIMIT 1", (target,)).fetchone()
        if season['status'] != 'paused' or not pause or pause['action_type'] != 'pause_season' or season['paused_at'] != pause['occurred_at'] or now < season['paused_at']:
            raise ValueError('Choose an administrator-paused season and a valid clock.')
        seconds = now - season['paused_at']
        for player in players:
            with account_scope(player['account_id']):
                state = read_state(c)
                if c.execute('SELECT 1 FROM admin_freezes WHERE settlement_id=?', (player['settlement_id'],)).fetchone():
                    # Its personal pause already includes this interval.
                    continue
                if state['settlement']['status'] == 'active':
                    shift_player(c, state, seconds, now)
                elif state['settlement']['suspended_at'] is not None:
                    shift_player(c, state, seconds, now)
                    c.execute('UPDATE settlements SET suspended_at=suspended_at+? WHERE settlement_id=?', (seconds, player['settlement_id']))
                    from game.simulation import _event
                    _event(c, state, 'prototype_supply_pause', state['settlement']['suspended_at']+seconds, state['resources'])
        status = json.loads(pause['before_values'])['status']
        c.execute('UPDATE seasons SET status=?,paused_at=NULL,finalization_at=finalization_at+?,ends_at=ends_at+? WHERE season_id=?', (status, seconds, seconds, target))
        release_timers(c, now)
    after = dict(c.execute('SELECT * FROM seasons WHERE season_id=?', (target,)).fetchone())
    audit(c, actor, action, 'season', target, now, reason, before, after, target)


def number(value, maximum, *, whole=False, positive=False):
    if type(value) not in (float, int) or not math.isfinite(value) or value < 0 or value > maximum or (positive and value == 0) or (whole and value != int(value)):
        raise ValueError(f'Use a {"positive" if positive else "nonnegative"}, finite {"whole " if whole else ""}value up to {maximum:g}.')
    return int(value) if whole else value


def correct(c, actor, action, sid, target, field, value, expected, now, reason):
    """Compare-and-set prevents a stale page silently overwriting newer progress."""
    from game.admin import audit
    from game.simulation import _advance, _event
    row = c.execute('SELECT * FROM settlements WHERE settlement_id=?', (sid,)).fetchone()
    if not row:
        raise ValueError('Choose an existing settlement.')
    with account_scope(row['account_id']):
        state = read_state(c)
        if state['settlement']['settlement_id'] != sid or state['settlement']['status'] == 'archived' or state['season']['status'] == 'finished':
            raise ValueError('Archived settlements cannot be corrected.')
        if now < state['settlement']['simulation_processed_at']:
            raise ValueError('The clock is earlier than the saved progress.')
        # Corrections require frozen time: their displayed before value is stable.
        if not frozen(c, state):
            raise ValueError('Pause the season or suspend this account before correcting it.')
        kind, identity, before, after = 'settlement', sid, {}, {}
        if action == 'correct_resource':
            from game.trading import RESOURCES, capacity_ok
            if field not in RESOURCES:
                raise ValueError('Choose Food, Water, Scrap, Metal, Electronics or Credits.')
            value = number(value, 1_000_000_000, whole=field == 'credits')
            previous = state['resources'][field]
            if value < state.get('reserved', {}).get(field, 0):
                raise ValueError('This correction would remove reserved resources. Resolve the offers first.')
            totals = {**state['resources'], field: value}
            if not capacity_ok(state, totals):
                raise ValueError('The correction exceeds current storage capacity.')
            before, after = {field: previous}, {field: value}
            c.execute(f'UPDATE settlement_resources SET {field}=?,updated_at=? WHERE settlement_id=?', (value, now, sid))
            if field == 'credits' and value != previous and state['expansion']:
                # Administrative issuance/removal is external, never a hidden Bank transfer.
                c.execute('''INSERT INTO credit_transactions(season_id,settlement_id,transfer_ref,transaction_type,amount,balance_after,occurred_at,transaction_data)
                    VALUES (?,?,?,'admin_correction',?,?,?,?)''', (row['season_id'], sid, f'admin:{actor}:{sid}:{now}:{c.execute("SELECT coalesce(max(admin_action_id),0)+1 FROM admin_actions").fetchone()[0]}', value-previous, value, now, json.dumps({'admin_account_id': actor, 'reason': reason})))
        elif action in ('correct_citizen_hp', 'correct_citizen_morale'):
            citizen = next((p for p in state['citizens'] if p['citizen_id'] == target), None)
            if not citizen or citizen.get('away'):
                raise ValueError('Choose a living citizen at home in this settlement.')
            field = 'current_hp' if action == 'correct_citizen_hp' else 'morale'
            from game.recovery import max_hp
            value = number(value, max_hp(state, citizen) if field == 'current_hp' else 100, positive=field == 'current_hp')
            previous = citizen[field]
            before, after = {field: previous}, {field: value}
            c.execute(f'UPDATE citizens SET {field}=? WHERE citizen_id=?', (value, target))
            if field == 'morale':
                c.execute("INSERT INTO citizen_morale_events(citizen_id,morale_before,morale_after,reason,occurred_at) VALUES (?,?,?,'admin_correction',?)", (target, previous, value, now))
            kind, identity = 'citizen', target
        elif action == 'correct_building_hp':
            building = next((b for b in state['buildings'] if b['building_id'] == target and b['status'] == 'active'), None)
            if not building or any(j['target_building_id'] == target and j['status'] in ('queued','active','paused') for j in state['jobs']):
                raise ValueError('Choose an active building without an unfinished project.')
            from game.buildings import spec, minimum_hp
            value = number(value, spec(state, building)['hp'], positive=True)
            if value < minimum_hp(state, building):
                raise ValueError('Town Hall HP must be at least 25% of its maximum.')
            previous = building['current_hp']
            before, after = {'current_hp': previous}, {'current_hp': value}
            c.execute('UPDATE buildings SET current_hp=? WHERE building_id=?', (value, target))
            kind, identity = 'building', target
        elif action == 'correct_attacks':
            from game.scoring import settings
            value = number(value, int(settings()['Citizen Economy']['attack_limit_daily']), whole=True)
            previous = state['settlement']['attacks_remaining']
            before, after = {'attacks_remaining': previous}, {'attacks_remaining': value}
            c.execute('UPDATE settlements SET attacks_remaining=? WHERE settlement_id=?', (value, sid))
        elif action == 'correct_debt':
            loan = c.execute("SELECT * FROM bank_loans WHERE loan_id=? AND settlement_id=? AND status IN ('active','liquidating')", (target, sid)).fetchone()
            if not loan:
                raise ValueError('Choose an outstanding loan from this settlement.')
            value = number(value, loan['original_principal']*2, whole=True)
            previous = loan['outstanding_balance']
            status = 'repaid' if value == 0 else 'liquidating' if value == loan['original_principal']*2 else 'active'
            before, after = {'outstanding_balance': previous, 'status': loan['status']}, {'outstanding_balance': value, 'status': status}
            c.execute('UPDATE bank_loans SET outstanding_balance=?,status=?,closed_at=? WHERE loan_id=?', (value, status, now if value == 0 else None, target))
            kind, identity = 'bank_loan', target
        else:
            raise ValueError('Unknown correction.')
        if type(expected) not in (float, int) or not math.isfinite(expected) or previous != expected:
            raise ValueError('The saved value changed. Reload the admin page before correcting it.')
        if previous == value:
            raise ValueError('The value is already correct.')
        audit(c, actor, action, kind, identity, now, reason, before, after, row['season_id'])
        _event(c, state, 'admin_correction', now, {'action': action, 'target_type': kind, 'target_id': identity, 'before': before, 'after': after})


def controls(c, token, form):
    from html import escape
    html = '<h2>Season controls</h2><p>Pausing freezes progression and shared timers. Resume extends the season by the paused duration.</p>'
    for season in c.execute("SELECT * FROM seasons WHERE status IN ('active','finalizing','paused') ORDER BY season_id DESC"):
        html += f'<p>Season #{season["season_id"]}: {escape(season["name"])} — {season["status"]}</p>'
        action = 'resume_season' if season['status'] == 'paused' else 'pause_season'
        html += form(token, action, f'<input type="hidden" name="target" value="{season["season_id"]}">')
    html += '<h2>Corrections</h2><p>Pause the season or suspend the account first, then reload this page. Each correction records its reason and before/after values. Reserved stock and storage limits are protected. HP corrections cannot kill, revive or rebuild; levels and balance settings stay unchanged.</p>'
    for row in c.execute("SELECT s.*,a.username FROM settlements s JOIN accounts a USING(account_id) WHERE s.status!='archived' ORDER BY s.settlement_id").fetchall():
        with account_scope(row['account_id']):
            state = read_state(c)
            if state['settlement']['settlement_id'] != row['settlement_id']:
                continue
            html += f'<details><summary>#{row["settlement_id"]} {escape(row["settlement_name"])} ({escape(row["username"])})</summary>'
            if not frozen(c, state):
                html += '<p>Freeze this player or season to make corrections.</p></details>'
                continue
            sid = f'<input type="hidden" name="settlement_id" value="{row["settlement_id"]}">'
            def correction(action, label, before, target=None, field=None):
                fields = sid+f'<p>{escape(label)}: {before:g}</p><input type="hidden" name="expected" value="{before}"><label>Replacement value <input name="value" type="number" step="any" min="0" required></label>'
                if target is not None: fields += f'<input type="hidden" name="target" value="{target}">'
                if field is not None: fields += f'<input type="hidden" name="field" value="{field}">'
                return form(token, action, fields)
            from game.trading import RESOURCES
            for resource in RESOURCES:
                html += correction('correct_resource', resource.title(), state['resources'][resource], field=resource)
            html += correction('correct_attacks', 'Attacks remaining', row['attacks_remaining'])
            for citizen in state['citizens']:
                if not citizen.get('away'):
                    html += correction('correct_citizen_hp', citizen['name']+' HP', citizen['current_hp'], citizen['citizen_id'])
                    html += correction('correct_citizen_morale', citizen['name']+' base morale', citizen['morale'], citizen['citizen_id'])
            for building in state['buildings']:
                if building['status'] == 'active':
                    html += correction('correct_building_hp', f'Building #{building["building_id"]} {building["building_type"]} HP', building['current_hp'], building['building_id'])
            for loan in c.execute("SELECT * FROM bank_loans WHERE settlement_id=? AND status IN ('active','liquidating')", (row['settlement_id'],)).fetchall():
                html += correction('correct_debt', f'Loan #{loan["loan_id"]} debt', loan['outstanding_balance'], loan['loan_id'])
            html += '</details>'
    return html

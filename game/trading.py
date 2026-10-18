"""Private trades backed by the V1 schema. All exchanges use one write transaction."""
from game.read_queries import read_connection
from contextlib import closing
from html import escape
import hashlib
import json
import math
import sqlite3

from database.create_database import connect_database
from game.settlement import CURRENT_ACCOUNT, account_scope, read_state

RESOURCES = ('food', 'water', 'scrap', 'metal', 'electronics', 'credits')
EXPIRY_SECONDS = 24 * 3600
MAX_OPEN = 10


def available(state, resource):
    quantity = state['resources'][resource] - state.get('reserved', {}).get(resource, 0)
    from game.buildings import expanded
    if resource == 'food' and expanded(state):
        from game.economy import food_lock
        quantity -= food_lock(state)['protected_food']
    return max(0, quantity)


def supply_frozen(connection, state):
    """Administrative suspension is never lifted by a trade."""
    if state['settlement']['status'] != 'suspended':
        return False
    row = connection.execute('''SELECT event_type,occurred_at FROM game_events
        WHERE settlement_id=? AND event_type IN
        ('prototype_supply_pause','settlement_suspended','settlement_resumed')
        ORDER BY event_id DESC LIMIT 1''', (state['settlement']['settlement_id'],)).fetchone()
    return bool(row and row['event_type'] == 'prototype_supply_pause'
                and row['occurred_at'] == state['settlement']['suspended_at'])


def resume_supplied(connection, state, now):
    if not supply_frozen(connection, state) or min(available(state, 'food'), available(state, 'water')) <= 1e-8:
        return
    if state['season']['status'] not in ('active', 'finalizing') or now >= state['season']['ends_at']:
        return
    seconds = now - state['settlement']['suspended_at']
    from game.recovery import shift_clock
    from game.simulation import _event
    shift_clock(connection, state, seconds, now)
    sid = state['settlement']['settlement_id']
    connection.execute('''UPDATE settlements SET status='active',suspended_at=NULL,
        simulation_processed_at=?,protection_until=protection_until+? WHERE settlement_id=?''', (now, seconds, sid))
    connection.execute('''UPDATE citizens SET unemployed_since=unemployed_since+?,
        homeless_since=homeless_since+? WHERE settlement_id=?''', (seconds, seconds, sid))
    _event(connection, state, 'prototype_supply_resumed', now, {})
    # Resuming after midnight must complete the reached rollover now, rather
    # than changing the same snapshot again on its next identical read.
    from game.combat import daily
    daily(connection, read_state(connection), now)


def expire(connection, state, now):
    """Called at the expiry boundary, before released stock can be consumed."""
    sid = state['settlement']['settlement_id']
    rows = connection.execute('''SELECT trade_id,expires_at FROM trade_proposals WHERE status='pending'
        AND proposer_settlement_id=? AND expires_at<=?''', (sid, now)).fetchall()
    changed = False
    for row in rows:
        from game.admin_controls import timer_frozen
        if timer_frozen(connection, 'trade', row['trade_id']):
            continue
        finish(connection, row['trade_id'], 'expired', row['expires_at'])
        changed = True
    if now >= state['season']['ends_at']:
        rows = connection.execute("SELECT trade_id FROM trade_proposals WHERE season_id=? AND status='pending'",
                                  (state['season']['season_id'],)).fetchall()
        changed = changed or bool(rows)
        for row in rows:
            finish(connection, row['trade_id'], 'expired', state['season']['ends_at'])
    if changed:
        resume_supplied(connection, read_state(connection), now)
    return changed


def next_expiry(connection, state):
    from game.admin_controls import table_exists
    if table_exists(connection, 'admin_timer_freezes'):
        row = connection.execute('''SELECT min(expires_at) FROM trade_proposals t
            WHERE proposer_settlement_id=? AND status='pending' AND expires_at>?
            AND NOT EXISTS(SELECT 1 FROM admin_timer_freezes f WHERE f.kind='trade' AND f.target_id=t.trade_id)''',
            (state['settlement']['settlement_id'], state['settlement']['simulation_processed_at'])).fetchone()
        return row[0] if row and row[0] is not None else None
    row = connection.execute('''SELECT min(expires_at) FROM trade_proposals
        WHERE proposer_settlement_id=? AND status='pending' AND expires_at>?''',
        (state['settlement']['settlement_id'], state['settlement']['simulation_processed_at'])).fetchone()
    return row[0]


def settle_incoming(connection, state, now):
    """A recipient's read also expires offers from players who are offline."""
    rows = connection.execute('''SELECT DISTINCT s.account_id FROM trade_proposals t
        JOIN settlements s ON s.settlement_id=t.proposer_settlement_id
        WHERE t.recipient_settlement_id=? AND t.status='pending' AND t.expires_at<=?''',
        (state['settlement']['settlement_id'], now)).fetchall()
    from game.simulation import _advance
    for row in rows:
        with account_scope(row['account_id']):
            _advance(connection, read_state(connection), now)
    return bool(rows)


def finish(connection, trade_id, status, now):
    connection.execute('UPDATE trade_proposals SET status=?,completed_at=? WHERE trade_id=?', (status, now, trade_id))
    connection.execute('''UPDATE resource_reservations SET released_at=?,release_reason=?
        WHERE trade_proposal_id=? AND released_at IS NULL''', (now, status, trade_id))


def validate_items(items):
    if not isinstance(items, dict) or not items:
        raise ValueError('Specify something to give and something to receive.')
    result = {}
    for resource, quantity in items.items():
        if resource not in RESOURCES or type(quantity) not in (int, float) or not math.isfinite(quantity) or not 0 < quantity <= 1_000_000_000:
            raise ValueError('Use positive, finite resource quantities up to one billion.')
        if resource == 'credits' and quantity != int(quantity):
            raise ValueError('Credits must be whole numbers.')
        result[resource] = int(quantity) if resource == 'credits' else quantity
    return result


def player_state(connection, sid, now):
    row = connection.execute('''SELECT s.account_id,a.is_active FROM settlements s
        JOIN accounts a USING(account_id) WHERE settlement_id=?''', (sid,)).fetchone()
    if not row or not row['is_active']:
        raise ValueError('Choose an active player settlement.')
    with account_scope(row['account_id']):
        state = read_state(connection)
        if not state or state['settlement']['settlement_id'] != sid:
            raise ValueError('That settlement is no longer current.')
        from game.simulation import _advance
        _advance(connection, state, now)
        return read_state(connection)


def eligible(connection, state, now, transactional=True):
    if not state or state['season']['status'] not in ('active', 'finalizing') or now >= state['season']['ends_at']:
        raise ValueError('Trading needs an active season.')
    if now < state['settlement']['simulation_processed_at']:
        raise ValueError('The clock is earlier than the saved state.')
    if state['settlement']['status'] != 'active' and not supply_frozen(connection, state):
        raise ValueError('This settlement cannot trade while suspended or archived.')
    if transactional and now >= state['season']['finalization_at']:
        raise ValueError('New exchanges are closed during the final three hours.')


def capacity_ok(state, totals):
    from game.economy import storage
    limits = storage(state)
    # Existing overflow may be retained, but a trade must not increase it.
    for resource in ('food', 'water'):
        if totals[resource] > max(limits[resource], state['resources'][resource]) + 1e-8:
            return False
    materials = ('scrap', 'metal', 'electronics')
    return sum(totals[r] for r in materials) <= max(limits['material'], sum(state['resources'][r] for r in materials)) + 1e-8


def transact(path, action, now, *, recipient_id=None, offered=None, requested=None, trade_id=None):
    """The current account is authoritative; submitted player IDs never select the actor."""
    if CURRENT_ACCOUNT.get() is None:
        raise ValueError('Log in to trade.')
    if action not in ('propose', 'accept', 'reject', 'cancel'):
        raise ValueError('Unknown trade action.')
    with closing(connect_database(path)) as connection, connection:
        connection.row_factory = sqlite3.Row
        connection.execute('BEGIN IMMEDIATE')
        state = read_state(connection)
        if state is None:
            raise ValueError('Create a settlement first.')
        sid = state['settlement']['settlement_id']
        if action == 'propose':
            offered, requested = validate_items(offered), validate_items(requested)
            if type(recipient_id) is not int or recipient_id == sid:
                raise ValueError('Choose another settlement.')
            state = player_state(connection, sid, now)
            other = player_state(connection, recipient_id, now)
            eligible(connection, state, now)
            eligible(connection, other, now)
            if state['season']['season_id'] != other['season']['season_id']:
                raise ValueError('Both settlements must be in the same season.')
            if connection.execute("SELECT count(*) FROM trade_proposals WHERE proposer_settlement_id=? AND status='pending'", (sid,)).fetchone()[0] >= MAX_OPEN:
                raise ValueError('Cancel or finish a proposal first: ten outgoing proposals are allowed.')
            if any(available(state, r) < quantity for r, quantity in offered.items()):
                raise ValueError('Not enough available resources to reserve this offer.')
            trade_id = connection.execute('''INSERT INTO trade_proposals
                (season_id,proposer_settlement_id,recipient_settlement_id,status,proposed_at,expires_at)
                VALUES (?,?,?,'pending',?,?)''', (state['season']['season_id'], sid, recipient_id, now, now + EXPIRY_SECONDS)).lastrowid
            for side, items in [('proposer', offered), ('recipient', requested)]:
                for resource, quantity in items.items():
                    connection.execute('INSERT INTO trade_items (trade_id,side,resource_type,quantity) VALUES (?,?,?,?)', (trade_id, side, resource, quantity))
                    if side == 'proposer':
                        connection.execute('''INSERT INTO resource_reservations
                            (settlement_id,resource_type,quantity,trade_proposal_id,created_at) VALUES (?,?,?,?,?)''', (sid, resource, quantity, trade_id, now))
            return trade_id
        trade = connection.execute('SELECT * FROM trade_proposals WHERE trade_id=?', (trade_id,)).fetchone()
        if not trade or sid not in (trade['proposer_settlement_id'], trade['recipient_settlement_id']):
            raise ValueError('Choose one of your own proposals.')
        expected = trade['proposer_settlement_id'] if action == 'cancel' else trade['recipient_settlement_id']
        if sid != expected:
            raise ValueError('Only the proposer can cancel; only the recipient can accept or reject.')
        if trade['status'] != 'pending':
            raise ValueError('This proposal has already finished.')
        one = player_state(connection, trade['proposer_settlement_id'], now)
        two = player_state(connection, trade['recipient_settlement_id'], now)
        trade = connection.execute('SELECT * FROM trade_proposals WHERE trade_id=?', (trade_id,)).fetchone()
        if trade['status'] != 'pending':
            return trade_id  # Persist expiry/end transitions, without executing an exchange.
        own = one if sid == trade['proposer_settlement_id'] else two
        eligible(connection, own, now, transactional=action == 'accept')
        if action != 'accept':
            finish(connection, trade_id, 'cancelled' if action == 'cancel' else 'rejected', now)
        else:
            eligible(connection, one, now)
            eligible(connection, two, now)
            items = connection.execute('SELECT * FROM trade_items WHERE trade_id=?', (trade_id,)).fetchall()
            offered = {r['resource_type']: r['quantity'] for r in items if r['side'] == 'proposer'}
            requested = {r['resource_type']: r['quantity'] for r in items if r['side'] == 'recipient'}
            reservations = {r['resource_type']: r['quantity'] for r in connection.execute('SELECT * FROM resource_reservations WHERE trade_proposal_id=? AND released_at IS NULL', (trade_id,))}
            if offered != reservations or any(one['resources'][r] + 1e-8 < one.get('reserved', {}).get(r, 0) for r in offered):
                raise ValueError('The offer reservation is no longer valid.')
            if any(available(two, r) < quantity for r, quantity in requested.items()):
                raise ValueError('Not enough available resources to accept this exchange.')
            new_one = {r: one['resources'][r] - offered.get(r, 0) + requested.get(r, 0) for r in RESOURCES}
            new_two = {r: two['resources'][r] - requested.get(r, 0) + offered.get(r, 0) for r in RESOURCES}
            if not capacity_ok(one, new_one) or not capacity_ok(two, new_two):
                raise ValueError('This exchange would exceed settlement storage. Free space first.')
            for owner, amounts in [(one, new_one), (two, new_two)]:
                owner_id = owner['settlement']['settlement_id']
                connection.execute('''UPDATE settlement_resources SET food=?,water=?,scrap=?,metal=?,electronics=?,credits=?,updated_at=? WHERE settlement_id=?''', tuple(int(amounts[r]) if r == 'credits' else amounts[r] for r in RESOURCES) + (now, owner_id))
                delta = int(amounts['credits'] - owner['resources']['credits'])
                if delta:
                    connection.execute('''INSERT INTO credit_transactions
                        (season_id,settlement_id,transfer_ref,transaction_type,amount,balance_after,occurred_at)
                        VALUES (?,?,?,'direct_trade',?,?,?)''', (owner['season']['season_id'], owner_id, f'trade:{trade_id}', delta, int(amounts['credits']), now))
                from game.simulation import _event
                _event(connection, owner, 'direct_trade_accepted', now, {'trade_id': trade_id})
            finish(connection, trade_id, 'accepted', now)
        for owner in (one, two):
            with account_scope(owner['settlement']['account_id']):
                resume_supplied(connection, read_state(connection), now)
        return trade_id


def panel(path, state, token):
    """Only participant proposals and public settlement names are exposed."""
    if not state:
        return ''
    sid, season = state['settlement']['settlement_id'], state['season']['season_id']
    hidden = f'<input type="hidden" name="token" value="{escape(token, quote=True)}">'
    with closing(connect_database(path)) as connection:
        connection.row_factory = sqlite3.Row
        players = connection.execute('''SELECT s.settlement_id,s.settlement_name FROM settlements s
            JOIN accounts a USING(account_id) WHERE season_id=? AND settlement_id!=?
            AND a.is_active=1 AND s.status IN ('active','suspended') ORDER BY s.settlement_name''', (season, sid)).fetchall()
        trades = connection.execute('''SELECT t.*,p.settlement_name AS proposer_name,r.settlement_name AS recipient_name
            FROM trade_proposals t JOIN settlements p ON p.settlement_id=t.proposer_settlement_id
            JOIN settlements r ON r.settlement_id=t.recipient_settlement_id
            WHERE t.season_id=? AND (proposer_settlement_id=? OR recipient_settlement_id=?)
            ORDER BY trade_id DESC LIMIT 30''', (season, sid, sid)).fetchall()
        html = '<section class="production-panel" id="trading"><h2>Player trading</h2><p>Fee-free exchanges. Offers reserve your resources for 24 hours; up to ten outgoing proposals.</p>'
        html += '<p>Available / reserved: ' + '; '.join(f'{r.title()} <span id="trade-available-{r}">{available(state,r):.2f}</span> / <span id="trade-reserved-{r}">{state.get("reserved",{}).get(r,0):.2f}</span>' for r in RESOURCES) + '.</p>'
        if players:
            options = ''.join(f'<option value="{p["settlement_id"]}">{escape(p["settlement_name"])}</option>' for p in players)
            resources = ''.join(f'<option value="{r}">{r.title()}</option>' for r in RESOURCES)
            html += f'''<form method="post" action="/trade" aria-label="Propose trade">{hidden}<input type="hidden" name="action" value="propose">
                <label>Trade with <select name="recipient_id">{options}</select></label>
                <label>Give <select name="offered_resource">{resources}</select><input aria-label="Give quantity" name="offered_quantity" type="number" min="0.01" max="1000000000" step="any" value="10" required></label>
                <label>Receive <select name="requested_resource">{resources}</select><input aria-label="Receive quantity" name="requested_quantity" type="number" min="0.01" max="1000000000" step="any" value="10" required></label><button>Propose trade</button></form>'''
        else:
            html += '<p>Another player must create a settlement in this season before you can trade.</p>'
        for trade in trades:
            items = connection.execute('SELECT side,resource_type,quantity FROM trade_items WHERE trade_id=? ORDER BY trade_item_id', (trade['trade_id'],)).fetchall()
            description = {side: ', '.join(f'{r["quantity"]:g} {r["resource_type"]}' for r in items if r['side'] == side) for side in ('proposer', 'recipient')}
            html += f'<div class="building-controls"><p>#{trade["trade_id"]}: {escape(trade["proposer_name"])} gives {description["proposer"]} to {escape(trade["recipient_name"])} for {description["recipient"]}. {trade["status"].title()}.</p>'
            if trade['status'] == 'pending':
                actions = ('cancel',) if trade['proposer_settlement_id'] == sid else ('accept', 'reject')
                for action in actions:
                    html += f'<form method="post" action="/trade">{hidden}<input type="hidden" name="action" value="{action}"><input type="hidden" name="trade_id" value="{trade["trade_id"]}"><button>{action.title()} trade #{trade["trade_id"]}</button></form>'
            html += '</div>'
        return html + '</section>'


def revision(path, state,*,connection=None):
    """Wake the existing page refresher when participant trades or players change."""
    sid, season = state['settlement']['settlement_id'], state['season']['season_id']
    with read_connection(path,connection,rows=False) as c:
        trades = c.execute('''SELECT trade_id,status FROM trade_proposals WHERE season_id=?
            AND (proposer_settlement_id=? OR recipient_settlement_id=?) ORDER BY trade_id''', (season,sid,sid)).fetchall()
        players = c.execute('''SELECT s.settlement_id,s.settlement_name,s.status,a.is_active FROM settlements s
            JOIN accounts a USING(account_id) WHERE season_id=? ORDER BY settlement_id''', (season,)).fetchall()
    return hashlib.sha256(json.dumps([trades,players]).encode()).hexdigest()[:16]

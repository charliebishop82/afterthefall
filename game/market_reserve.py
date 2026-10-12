"""Finite daily NPC goods; allowances belong to settlements, not accounts."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3

from database.create_database import connect_database
from game import social, trading

CONFIG = Path(__file__).resolve().parents[1] / 'config' / 'market_reserve.json'
RESOURCES = ('food', 'water', 'scrap', 'metal', 'electronics')


def settings():
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    if type(config.get('enabled')) is not bool:
        raise ValueError('Market reserve enabled must be true or false.')
    for resource in RESOURCES:
        row = config['resources'][resource]
        for key in ('daily_quantity', 'unit_price'):
            value = row[key]
            minimum = 0 if key == 'daily_quantity' else 1
            if type(value) is not int or not minimum <= value <= 1_000_000:
                raise ValueError('Invalid market reserve quantity or price.')
    return config


def prepare(c):
    # Execute within the caller's transaction; never use executescript here.
    c.execute('''CREATE TABLE IF NOT EXISTS market_reserve_purchases (
        purchase_id INTEGER PRIMARY KEY,
        settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
        season_id INTEGER NOT NULL REFERENCES seasons(season_id),
        day INTEGER NOT NULL, resource TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK(quantity>0),
        unit_price INTEGER NOT NULL CHECK(unit_price>0),
        occurred_at INTEGER NOT NULL)''')
    c.execute('''CREATE INDEX IF NOT EXISTS reserve_allowance
        ON market_reserve_purchases(settlement_id,day,resource)''')


def remaining(c, sid, day, config):
    used = {}
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='market_reserve_purchases'").fetchone():
        used = dict(c.execute('''SELECT resource,sum(quantity) FROM market_reserve_purchases
            WHERE settlement_id=? AND day=? GROUP BY resource''', (sid,day)))
    return {r:max(0,config['resources'][r]['daily_quantity']-used.get(r,0)) for r in RESOURCES}


def purchase(c, state, resource, quantity, now):
    from game.market import whole, MAX_VALUE
    from game import banking
    from game.settlement import read_state
    from game.simulation import _event
    config = settings()
    if not config['enabled']:
        raise ValueError('The market reserve is disabled.')
    if resource not in RESOURCES:
        raise ValueError('Choose a market reserve resource.')
    whole(quantity)
    sid = state['settlement']['settlement_id']
    day = now // 86400
    if quantity > remaining(c,sid,day,config)[resource]:
        raise ValueError('Not enough daily allowance remains for this resource.')
    price = config['resources'][resource]['unit_price']
    total = quantity * price
    if total > MAX_VALUE or trading.available(state,'credits') < total:
        raise ValueError('Not enough available Credits, or purchase exceeds the transaction limit.')
    incoming = dict(state['resources']); incoming[resource] += quantity
    if not trading.capacity_ok(state,incoming):
        raise ValueError('Free storage space before purchasing.')
    prepare(c)
    pid = c.execute('''INSERT INTO market_reserve_purchases
        (settlement_id,season_id,day,resource,quantity,unit_price,occurred_at)
        VALUES (?,?,?,?,?,?,?)''',(sid,state['season']['season_id'],day,resource,quantity,price,now)).lastrowid
    data = dict(purchase_id=pid,resource=resource,quantity=quantity,unit_price=price,day=day)
    banking.transfer(c,state,-total,now,'market',f'market-reserve:{pid}',data)
    # Resource is restricted to the fixed allow-list above.
    c.execute(f'UPDATE settlement_resources SET {resource}={resource}+?,updated_at=? WHERE settlement_id=?',
              (quantity,now,sid))
    _event(c,state,'market_reserve_purchase',now,data)
    social.notify(c,state['settlement']['account_id'],state['season']['season_id'],'market',
                  f'Market reserve: bought {quantity} {resource} for {total} Credits.',now)
    trading.resume_supplied(c,read_state(c),now)
    return pid


def panel(path, state, token, now):
    config = settings()
    if not config['enabled']:
        return ''
    sid = state['settlement']['settlement_id']
    with closing(connect_database(path)) as c:
        allowance = remaining(c,sid,now//86400,config)
        history = []
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='market_reserve_purchases'").fetchone():
            history = c.execute('''SELECT quantity,resource,unit_price,occurred_at FROM market_reserve_purchases
                WHERE settlement_id=? ORDER BY purchase_id DESC LIMIT 10''',(sid,)).fetchall()
    reset = datetime.fromtimestamp((now//86400+1)*86400,timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    html = ('<div class="building-controls"><h3>Daily market reserve</h3>'
            f'<p>Your settlement’s remaining allowance. Resets {reset}; unused stock does not carry over. '
            'Available even without player listings. Prices include all charges.</p>')
    for r in RESOURCES:
        price = config['resources'][r]['unit_price']; left = allowance[r]
        incoming = dict(state['resources']); incoming[r] += 1
        reason = ('Daily allowance used' if not left else 'Not enough Credits' if trading.available(state,'credits') < price
                  else 'Storage full' if not trading.capacity_ok(state,incoming) else '')
        html += f'<p>{r.title()}: {left} units remaining · {price} Credits each.</p>'
        if reason:
            html += f'<p>{reason}</p>'
        else:
            html += social.form(token,'market','reserve_buy',social.hidden('resource',r)+
                f'<label>Quantity <input name="quantity" type="number" min="1" max="{left}" value="1" required></label>'
                f'<button>Buy {r.title()}</button></form>')
    if history:
        html += '<details><summary>Recent reserve purchases</summary>'
        for quantity,resource,price,at in history:
            timestamp = datetime.fromtimestamp(at,timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
            html += f'<p>{timestamp}: {quantity} {resource}, {quantity*price} Credits.</p>'
        html += '</details>'
    return html+'</div>'

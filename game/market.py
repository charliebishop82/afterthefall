"""Season-wide pooled stock, immediate Bank-backed sales and purchases."""
from game.read_queries import read_connection
from contextlib import closing
from decimal import Decimal, ROUND_CEILING
from html import escape
from pathlib import Path
import json
import sqlite3
from database.create_database import connect_database
from game import social, trading, diplomacy, banking
from game.settlement import read_state

RESOURCES = trading.RESOURCES[:-1]
MAX_VALUE = 1_000_000_000
CONFIG = Path(__file__).resolve().parents[1] / 'config/market_pool.json'


def whole(value):
    if type(value) is not int or not 1 <= value <= MAX_VALUE:
        raise ValueError('Use positive whole quantities and prices up to one billion.')
    return value


def settings():
    from game.market_reserve import settings as reserve_settings
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    reserve = reserve_settings()
    for r in RESOURCES:
        prices = config[r]
        whole(prices['buy_price']); whole(prices['sell_price'])
        # No profitable buy-and-resell loop, including the personal reserve.
        if prices['sell_price'] >= min(prices['buy_price'],reserve['resources'][r]['unit_price']):
            raise ValueError('Market selling prices must be below shared and reserve buying prices.')
    return config


def close_listing(c, listing_id, now, reason='cancelled'):
    """Historical compatibility for liquidation and end-of-season cleanup."""
    c.execute("UPDATE market_listings SET status=?,closed_at=? WHERE listing_id=? AND status='open'",(reason,now,listing_id))
    c.execute('UPDATE resource_reservations SET released_at=?,release_reason=? WHERE market_listing_id=? AND released_at IS NULL',(now,reason,listing_id))


def finish_season(c, season, now):
    for row in c.execute("SELECT listing_id FROM market_listings WHERE season_id=? AND status='open'",(season,)).fetchall():
        close_listing(c,row[0],now)


def prepare(c, now):
    """Additive, idempotent upgrade; retain old history and release unsold goods."""
    c.execute('''CREATE TABLE IF NOT EXISTS market_pool_stock (
        season_id INTEGER NOT NULL REFERENCES seasons(season_id),
        resource TEXT NOT NULL CHECK(resource IN ('food','water','scrap','metal','electronics')),
        quantity INTEGER NOT NULL CHECK(quantity>=0), updated_at INTEGER NOT NULL,
        PRIMARY KEY(season_id,resource))''')
    c.execute('''CREATE TABLE IF NOT EXISTS market_pool_trades (
        trade_id INTEGER PRIMARY KEY, season_id INTEGER NOT NULL REFERENCES seasons(season_id),
        settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
        action TEXT NOT NULL CHECK(action IN ('buy','sell')),
        resource TEXT NOT NULL CHECK(resource IN ('food','water','scrap','metal','electronics')),
        quantity INTEGER NOT NULL CHECK(quantity>0), unit_price INTEGER NOT NULL CHECK(unit_price>0),
        fee INTEGER NOT NULL CHECK(fee>=0), credit_amount INTEGER NOT NULL,
        occurred_at INTEGER NOT NULL)''')
    c.execute('CREATE INDEX IF NOT EXISTS pool_trade_history ON market_pool_trades(settlement_id,trade_id)')
    for lid,season,sid in c.execute("SELECT listing_id,season_id,seller_settlement_id FROM market_listings WHERE status='open'").fetchall():
        close_listing(c,lid,now)
        c.execute('''INSERT INTO game_events(season_id,settlement_id,event_type,occurred_at,event_data)
            VALUES (?,?,'market_listing_migrated',?,?)''',
            (season,sid,now,json.dumps({'listing_id':lid,'action':'cancelled','reason':'Pooled market replaces individual listings'})))


def stock(c, season):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='market_pool_stock' AND type='table'").fetchone():
        return dict.fromkeys(RESOURCES,0)
    rows=dict(c.execute('SELECT resource,quantity FROM market_pool_stock WHERE season_id=?',(season,)))
    return {r:rows.get(r,0) for r in RESOURCES}


def selling_fee(state, gross):
    from game.support import best
    reduction = max(0,min(100,best(state,'market_fee_reduction')))
    rate = max(Decimal(str(diplomacy.rule('market_min_fee'))),
               Decimal(str(diplomacy.rule('market_base_fee')))*(1-Decimal(str(reduction))/100))
    return int((Decimal(gross)*rate/100).to_integral_value(rounding=ROUND_CEILING))


def transact(path, action, now, *, resource=None, quantity=None, unit_price=None, listing_id=None):
    if action not in ('sell','buy','reserve_buy'):
        raise ValueError('Individual listings have been replaced. Refresh and choose Buy or Sell in the shared market.')
    # Legacy request fields cannot silently execute a different transaction.
    if listing_id is not None or unit_price is not None:
        raise ValueError('Market prices are fixed. Refresh the market page.')
    with social.transaction(path,now) as (c,state):
        prepare(c,now)
        if action=='reserve_buy':
            from game.market_reserve import purchase
            return purchase(c,state,resource,quantity,now)
        whole(quantity)
        if resource not in RESOURCES: raise ValueError('Choose a market resource.')
        prices=settings()[resource]
        sid=state['settlement']['settlement_id'];season=state['season']['season_id']
        price=prices['sell_price' if action=='sell' else 'buy_price'];gross=quantity*price
        if gross>MAX_VALUE: raise ValueError('A market transaction may use at most one billion Credits.')
        charge=selling_fee(state,gross) if action=='sell' else 0
        amount=gross-charge if action=='sell' else -gross
        if action=='sell':
            if trading.available(state,resource)+1e-8<quantity:
                raise ValueError('Not enough unreserved goods to sell.')
            if amount<=0: raise ValueError('Sell a larger quantity so proceeds exceed the rounded seller fee.')
        else:
            if stock(c,season)[resource]<quantity: raise ValueError('Not enough shared market stock. Try the daily reserve.')
            if trading.available(state,'credits')<gross: raise ValueError('Not enough available Credits.')
            incoming=dict(state['resources']);incoming[resource]+=quantity
            if not trading.capacity_ok(state,incoming): raise ValueError('Free storage space before purchasing.')
        tid=c.execute('''INSERT INTO market_pool_trades
            (season_id,settlement_id,action,resource,quantity,unit_price,fee,credit_amount,occurred_at)
            VALUES (?,?,?,?,?,?,?,?,?)''',(season,sid,action,resource,quantity,price,charge,amount,now)).lastrowid
        if action=='sell':
            c.execute('''INSERT INTO market_pool_stock(season_id,resource,quantity,updated_at) VALUES (?,?,?,?)
                ON CONFLICT(season_id,resource) DO UPDATE SET quantity=quantity+excluded.quantity,updated_at=excluded.updated_at''',
                (season,resource,quantity,now))
        else:
            c.execute('UPDATE market_pool_stock SET quantity=quantity-?,updated_at=? WHERE season_id=? AND resource=?',
                      (quantity,now,season,resource))
        delta=-quantity if action=='sell' else quantity
        c.execute(f'UPDATE settlement_resources SET {resource}={resource}+?,updated_at=? WHERE settlement_id=?',(delta,now,sid))
        data=dict(trade_id=tid,action=action,resource=resource,quantity=quantity,unit_price=price,fee=charge)
        banking.transfer(c,state,amount,now,'market',f'market-pool:{tid}',data)
        from game.simulation import _event
        _event(c,state,'market_pool_trade',now,data)
        social.notify(c,state['settlement']['account_id'],season,'market',
                      f'Shared market: {action} {quantity} {resource}; Credit change {amount:+}; seller fee {charge}.',now)
        trading.resume_supplied(c,read_state(c),now)
        return tid


def panel(path,state,token,now):
    from game.market_reserve import panel as reserve_panel
    prices=settings();sid=state['settlement']['settlement_id'];season=state['season']['season_id']
    with closing(connect_database(path)) as c:
        inventory=stock(c,season);history=[]
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='market_pool_trades'").fetchone():
            history=c.execute('''SELECT action,resource,quantity,unit_price,fee,credit_amount,occurred_at
                FROM market_pool_trades WHERE settlement_id=? ORDER BY trade_id DESC LIMIT 20''',(sid,)).fetchall()
        legacy=c.execute('''SELECT quantity,total_price,fee,occurred_at FROM market_transactions
            WHERE season_id=? AND (buyer_settlement_id=? OR seller_settlement_id=?)
            ORDER BY market_transaction_id DESC LIMIT 20''',(season,sid,sid)).fetchall()
    html=('<section class="production-panel" id="market"><h2>Public market</h2>'
          '<p>Shared stock comes from player sales. Sell immediately to the Bank; buy at fixed prices. '
          'There are no individual listings or delivery delays. The seller pays an 8% fee, reduced by '
          'their strongest functioning Trading Post (minimum 2%), rounded up to whole Credits. '
          'Trade agreements do not change pooled-market prices or fees.</p>')
    html+='<h3>Shared inventory</h3>'
    for r in RESOURCES:
        buy=prices[r]['buy_price'];sell=prices[r]['sell_price'];count=inventory[r]
        html+=f'<div class="building-controls"><h4>{r.title()}</h4><p>{count} available · Buy {buy} Credits/unit · Sell {sell} Credits/unit before fee.</p>'
        if count:
            html+=social.form(token,'market','buy',social.hidden('resource',r)+f'<label>Buy quantity <input name="quantity" type="number" min="1" max="{count}" value="1" required></label><button>Buy {r.title()}</button></form>')
        else: html+='<p>Shared stock empty. Check your daily reserve below.</p>'
        available=min(MAX_VALUE,int(trading.available(state,r)))
        if available:
            html+=social.form(token,'market','sell',social.hidden('resource',r)+f'<label>Sell quantity <input name="quantity" type="number" min="1" max="{available}" value="{min(10,available)}" required></label><button>Sell {r.title()}</button></form>')
        else: html+='<p>No unreserved goods to sell.</p>'
        html+='</div>'
    html+=reserve_panel(path,state,token,now)
    from game.equipment_market import panel as equipment_panel
    html+=equipment_panel(path,state,token,now)
    html+='<details><summary>Your recent shared-market transactions</summary>'
    from datetime import datetime,timezone
    for action,r,q,p,fee,amount,at in history:
        stamp=datetime.fromtimestamp(at,timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        html+=f'<p>{stamp}: {action.title()} {q} {escape(r)} × {p} Credits; Credit change {amount:+}; fee {fee}.</p>'
    html+='</details>'
    if legacy:
        html+='<details><summary>Historical listing-market transactions</summary>'
        for q,total,fee,at in legacy: html+=f'<p>{q} units; total {total} Credits; seller fee {fee}; timestamp {at}.</p>'
        html+='</details>'
    return html+'</section>'


def public_snapshot(path,state,now,*,connection=None):
    """Exactly the pool/prices and own allowance a normal player can inspect."""
    from game.market_reserve import settings as reserve_settings, remaining
    reserve=reserve_settings();prices=settings()
    with read_connection(path,connection,rows=True) as c:
        pool=stock(c,state['season']['season_id'])
        allowance=remaining(c,state['settlement']['settlement_id'],now//86400,reserve)
        from game.equipment_market import public_snapshot as equipment_snapshot
        equipment=equipment_snapshot(c,state,now)
        try:
            trading.eligible(c,state,now)
            can_trade=True
        except ValueError:
            can_trade=False
    return dict(can_trade=can_trade,equipment=equipment,resources={r:dict(stock=pool[r],**prices[r],
        reserve_remaining=allowance[r] if reserve['enabled'] else 0,
        reserve_price=reserve['resources'][r]['unit_price']) for r in RESOURCES})

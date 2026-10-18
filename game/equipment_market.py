"""Atomic pooled equipment trades and separate settlement daily reserves."""
from game.read_queries import read_connection
from contextlib import closing
from html import escape
import hashlib
import json
from pathlib import Path

from database.create_database import connect_database
from game import banking, manufacturing, social, trading

CONFIG=Path(__file__).resolve().parents[1]/'config/equipment_market.json'
KINDS=('offensive_drone','air_defense_drone','ground_defense_drone','repair_drone','missile','interceptor')


def settings():
    rows=json.loads(CONFIG.read_text(encoding='utf-8'))
    for kind in KINDS:
        row=rows[kind]
        if any(type(row[k]) is not int or not 1<=row[k]<=1_000_000 for k in ('buy_price','sell_price','reserve_price','daily_quantity')):
            raise ValueError('Invalid equipment market configuration.')
        if row['sell_price']>=min(row['buy_price'],row['reserve_price']):
            raise ValueError('Equipment selling prices must be lower than purchasing prices.')
    return rows


def prepare(c):
    c.execute('''CREATE TABLE IF NOT EXISTS equipment_market_stock (
        season_id INTEGER NOT NULL REFERENCES seasons(season_id),kind TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK(quantity>=0),PRIMARY KEY(season_id,kind))''')
    c.execute('''CREATE TABLE IF NOT EXISTS equipment_market_trades (
        trade_id INTEGER PRIMARY KEY,season_id INTEGER NOT NULL REFERENCES seasons(season_id),
        settlement_id INTEGER NOT NULL REFERENCES settlements(settlement_id),
        action TEXT NOT NULL CHECK(action IN ('buy','sell','reserve_buy')),kind TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK(quantity>0),unit_price INTEGER NOT NULL,
        fee INTEGER NOT NULL,credit_amount INTEGER NOT NULL,day INTEGER NOT NULL,
        occurred_at INTEGER NOT NULL,unit_ids TEXT NOT NULL)''')
    c.execute('CREATE INDEX IF NOT EXISTS equipment_allowance ON equipment_market_trades(settlement_id,day,kind,action)')


def snapshot(c,state,now):
    config=settings();season=state['season']['season_id'];sid=state['settlement']['settlement_id']
    exists=c.execute("SELECT 1 FROM sqlite_master WHERE name='equipment_market_trades'").fetchone()
    pool={};used={};history=[]
    if exists:
        pool=dict(c.execute('SELECT kind,quantity FROM equipment_market_stock WHERE season_id=?',(season,)))
        used=dict(c.execute("SELECT kind,sum(quantity) FROM equipment_market_trades WHERE settlement_id=? AND season_id=? AND day=? AND action='reserve_buy' GROUP BY kind",(sid,season,now//86400)))
        history=c.execute('SELECT action,kind,quantity,credit_amount,occurred_at FROM equipment_market_trades WHERE settlement_id=? ORDER BY trade_id DESC LIMIT 20',(sid,)).fetchall()
    return {k:dict(config[k],stock=pool.get(k,0),remaining=max(0,config[k]['daily_quantity']-used.get(k,0))) for k in KINDS},history


def public_snapshot(c,state,now):
    """Public stock plus only this player's reserve, capacity and saleable units."""
    if not manufacturing.enabled(state) or not state.get('expansion'):return {}
    from game.economy import utilities
    rows,_=snapshot(c,state,now);status=utilities(state)['buildings']
    for kind,row in rows.items():
        row['free_slots']=sum(n for _,n in slots(state,kind,status=status))
        own=sellable(state,kind)
        row['sellable']=len(own) if state['config']['units'][kind]['category']=='Drone' else sum(i['quantity'] for i in own)
    return rows


def revision(path,state,now,*,connection=None):
    """Reuse the existing Update panels signal when shared stock changes."""
    with read_connection(path,connection,rows=False) as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='equipment_market_stock'").fetchone():return ''
        rows=c.execute('SELECT kind,quantity FROM equipment_market_stock WHERE season_id=? ORDER BY kind',(state['season']['season_id'],)).fetchall()
        latest=c.execute('SELECT max(trade_id) FROM equipment_market_trades WHERE settlement_id=?',(state['settlement']['settlement_id'],)).fetchone()[0]
    return hashlib.sha256(json.dumps([rows,latest,now//86400]).encode()).hexdigest()[:16]


def sellable(state,kind):
    if state['config']['units'][kind]['category']=='Drone':
        busy={j['target_unit_id'] for j in state['jobs'] if j.get('target_unit_id') and j['status'] in ('queued','active','paused')}
        return sorted((u for u in state['units'] if u['unit_type']==kind and u['status']=='available'
                       and u['current_hp']>=state['config']['units'][kind]['hp'] and u['unit_id'] not in busy
                       and state.get('repair_drone_orders',{}).get(str(u['unit_id']),{}).get('mode') not in ('auto','manual')),key=lambda u:u['unit_id'])
    return sorted((i for i in state['inventory'] if i['unit_type']==kind and i['quantity']>0),key=lambda i:i['inventory_id'])


def slots(state,kind,*,status=None):
    from game.economy import utilities
    if status is None:status=utilities(state)['buildings']
    return [(b['building_id'],max(0,manufacturing.capacity(state,b)-manufacturing.occupancy(state,b['building_id'])))
            for b in state['buildings'] if manufacturing.compatible_home(state,kind,b)
            and b['status']=='active' and not status[b['building_id']]['reason']]


def transact(path,action,now,*,unit_type=None,quantity=None):
    from game.market import selling_fee, MAX_VALUE
    from game.simulation import _event
    if action not in ('equipment_buy','equipment_sell','equipment_reserve_buy') or unit_type not in KINDS:
        raise ValueError('Choose an equipment market action and type.')
    if type(quantity) is not int or not 1<=quantity<=10000:
        raise ValueError('Choose between 1 and 10000 whole equipment units.')
    operation=action.removeprefix('equipment_')
    with social.transaction(path,now) as (c,state):
        if not manufacturing.enabled(state) or not state.get('expansion'):raise ValueError('Military equipment trading requires the military and Bank systems in this save.')
        prepare(c)
        rows,_=snapshot(c,state,now);row=rows[unit_type]
        price=row['sell_price' if operation=='sell' else 'reserve_price' if operation=='reserve_buy' else 'buy_price']
        gross=price*quantity
        if gross>MAX_VALUE:raise ValueError('Equipment transaction exceeds the Credit limit.')
        fee=selling_fee(state,gross) if operation=='sell' else 0
        amount=gross-fee if operation=='sell' else -gross
        sid=state['settlement']['settlement_id'];season=state['season']['season_id'];ids=[]
        if operation=='sell':
            owned=sellable(state,unit_type);drone=state['config']['units'][unit_type]['category']=='Drone'
            count=len(owned) if drone else sum(i['quantity'] for i in owned)
            if count<quantity:raise ValueError('Not enough saleable equipment. Drones must be fully repaired, stored and idle.')
            if amount<=0:raise ValueError('Sale proceeds must exceed the seller fee.')
            left=quantity
            for item in owned:
                if not left:break
                if drone:
                    # Retain referenced unit history, but retire the sold unit
                    # from gameplay. The trade audit distinguishes sale from loss.
                    c.execute("UPDATE military_units SET status='destroyed',current_hp=0,destroyed_at=? WHERE unit_id=?",(now,item['unit_id']))
                    ids.append(item['unit_id']);left-=1
                else:
                    take=min(left,item['quantity']);left-=take
                    c.execute('UPDATE military_inventory SET quantity=quantity-?,updated_at=? WHERE inventory_id=?',(take,now,item['inventory_id']))
            c.execute('INSERT INTO equipment_market_stock VALUES (?,?,?) ON CONFLICT(season_id,kind) DO UPDATE SET quantity=quantity+excluded.quantity',(season,unit_type,quantity))
        else:
            if quantity>row['remaining' if operation=='reserve_buy' else 'stock']:
                raise ValueError('Not enough daily allowance or shared equipment stock remains.')
            if trading.available(state,'credits')<gross:raise ValueError('Not enough available Credits.')
            homes=slots(state,unit_type)
            if sum(n for _,n in homes)<quantity:raise ValueError('Build compatible equipment storage or free operational slots first.')
            left=quantity;unit=state['config']['units'][unit_type]
            for bid,space in homes:
                take=min(left,space);left-=take
                if not take:continue
                if unit['category']=='Drone':
                    for _ in range(take):
                        ids.append(c.execute("INSERT INTO military_units(settlement_id,unit_type,current_hp,home_building_id,status,created_at) VALUES (?,?,?,?,'available',?)",(sid,unit_type,unit['hp'],bid,now)).lastrowid)
                else:
                    c.execute('''INSERT INTO military_inventory(settlement_id,building_id,unit_type,quantity,updated_at) VALUES (?,?,?,?,?)
                        ON CONFLICT(building_id,unit_type) DO UPDATE SET quantity=quantity+excluded.quantity,updated_at=excluded.updated_at''',(sid,bid,unit_type,take,now))
            if operation=='buy':
                c.execute('UPDATE equipment_market_stock SET quantity=quantity-? WHERE season_id=? AND kind=?',(quantity,season,unit_type))
        tid=c.execute('''INSERT INTO equipment_market_trades(season_id,settlement_id,action,kind,quantity,unit_price,fee,credit_amount,day,occurred_at,unit_ids)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)''',(season,sid,operation,unit_type,quantity,price,fee,amount,now//86400,now,json.dumps(ids))).lastrowid
        data=dict(trade_id=tid,action=operation,unit_type=unit_type,quantity=quantity,unit_price=price,fee=fee,credit_amount=amount,unit_ids=ids)
        banking.transfer(c,state,amount,now,'market',f'equipment-market:{tid}',data)
        _event(c,state,'equipment_market_trade',now,data)
        social.notify(c,state['settlement']['account_id'],season,'market',f'Equipment market: {operation} {quantity} {unit_type}; Credits {amount:+}; fee {fee}.',now)
        return tid


def panel(path,state,token,now):
    if not manufacturing.enabled(state) or not state.get('expansion'):return ''
    with closing(connect_database(path)) as c:
        rows,history=snapshot(c,state,now)
    html='<div id="equipment-market"><h3>Military equipment</h3><p>Player sales supply shared stock. Your separate daily reserve resets at midnight UTC without accumulating. Purchases need operational storage, but no factory. Only fully repaired, idle stored drones can be sold. Seller fees match the resource market.</p>'
    from game.economy import utilities
    status=utilities(state)['buildings']
    for kind,row in rows.items():
        name=escape(state['config']['units'][kind]['name']);homes=slots(state,kind,status=status);room=sum(n for _,n in homes)
        owned=sellable(state,kind);count=len(owned) if state['config']['units'][kind]['category']=='Drone' else sum(i['quantity'] for i in owned)
        html+=f'<details><summary>{name} · Shared {row["stock"]} · Daily {row["remaining"]} · Free slots {room}</summary>'
        starter=state['config']['units'][kind].get('starter_storage')
        if starter and not room:
            html+=f'<p>Needs free operational storage: {escape(state["config"]["buildings"][starter]["name"])} (Town Hall 1), or its larger counterpart. <a href="#screen-build">Build storage</a>.</p>'
        for action,label,limit,price in [('buy','Buy shared',min(room,row['stock']),row['buy_price']),('reserve_buy','Buy daily reserve',min(room,row['remaining']),row['reserve_price']),('sell','Sell',count,row['sell_price'])]:
            if action!='sell':limit=min(limit,int(trading.available(state,'credits')//price))
            fields=social.hidden('unit_type',kind)+f'<label>{label}: {price} Credits/unit'+(' before fee' if action=='sell' else '')+f' <input name="quantity" type="number" min="1" max="{max(1,min(10000,limit))}" value="1" required'+(' disabled' if limit<=0 else '')+'></label><button'+(' disabled' if limit<=0 else '')+'>'+label+'</button></form>'
            html+=social.form(token,'market','equipment_'+action,fields)
        html+='</details>'
    if history:
        html+='<details><summary>Your recent equipment trades</summary>'
        from datetime import datetime,timezone
        for action,kind,q,amount,at in history:
            stamp=datetime.fromtimestamp(at,timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
            html+=f'<p>{stamp}: {escape(action)} {q} {escape(kind)}; Credits {amount:+}.</p>'
        html+='</details>'
    return html+'</div>'

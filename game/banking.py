"""Small auditable Bank primitives; amounts are whole Credits."""
import json
import math
from game.scoring import settings, resources_value, buildings_value


def rule(key):
    return settings()['Economy Diplomacy'][key]


def loans(connection, sid):
    return [dict(r) for r in connection.execute("SELECT * FROM bank_loans WHERE settlement_id=? AND (status IN ('active','liquidating') OR (status='settled' AND outstanding_balance>0)) ORDER BY loan_id", (sid,))]


def investments(connection, sid):
    return [dict(r) for r in connection.execute("SELECT * FROM bank_investments WHERE settlement_id=? AND status='active' ORDER BY investment_id", (sid,))]


def debt(connection, sid):
    return sum(row['outstanding_balance'] for row in loans(connection, sid))


def principal(connection, sid):
    total = 0
    for loan in loans(connection, sid):
        paid = connection.execute("SELECT coalesce(sum(json_extract(transaction_data,'$.principal_paid')),0) FROM credit_transactions WHERE settlement_id=? AND transaction_type='loan_repayment' AND json_extract(transaction_data,'$.loan_id')=?", (sid, loan['loan_id'])).fetchone()[0]
        total += min(loan['outstanding_balance'], max(0, loan['original_principal'] - paid))
    return total


def value(connection, state):
    return max(0, resources_value(state, 'settlement') + buildings_value(state)
               + max(0,state['resources']['credits']-state.get('reserved',{}).get('credits',0)) - debt(connection, state['settlement']['settlement_id']))


def health(connection, season):
    reserve = connection.execute('SELECT credits FROM season_bank WHERE season_id=?', (season,)).fetchone()[0]
    obligations = connection.execute("SELECT coalesce(sum(principal+accrued_interest),0) FROM bank_investments WHERE season_id=? AND status='active'", (season,)).fetchone()[0]
    ratio = max(0, reserve) / obligations if obligations else (1 if reserve>=0 else 0)
    good = rule('bank_health_good') / 100
    stressed = rule('bank_health_stressed') / 100
    pressure = min(1, max(0, (good-ratio) / (good-stressed)))
    return dict(reserve=reserve, obligations=obligations, ratio=ratio, pressure=pressure,
                loan_rate=rule('loan_base_interest')+rule('bank_loan_rate_stress_max')*pressure)


def transfer(connection, state, amount, now, kind, reference, data=None):
    """Positive amount pays the player; negative pays the Bank, with paired rows."""
    if not amount:
        return
    if type(amount) is not int:
        raise ValueError('Credits must be whole numbers.')
    sid=state['settlement']['settlement_id'];season=state['season']['season_id']
    current=connection.execute('SELECT credits FROM settlement_resources WHERE settlement_id=?',(sid,)).fetchone()[0]
    if current+amount<0:
        raise ValueError('Insufficient Credits.')
    connection.execute('UPDATE settlement_resources SET credits=credits+?,updated_at=? WHERE settlement_id=?',(amount,now,sid))
    connection.execute('UPDATE season_bank SET credits=credits-?,updated_at=? WHERE season_id=?',(amount,now,season))
    reserve=connection.execute('SELECT credits FROM season_bank WHERE season_id=?',(season,)).fetchone()[0]
    for owner, change, balance in ((sid,amount,current+amount),(None,-amount,reserve)):
        connection.execute('''INSERT INTO credit_transactions(season_id,settlement_id,transfer_ref,transaction_type,amount,balance_after,occurred_at,transaction_data)
            VALUES (?,?,?,?,?,?,?,?)''',(season,owner,reference,kind,change,balance,now,json.dumps(data or {})))

    from game.simulation import _event
    _event(connection,state,'bank_transaction',now,{'kind':kind,'amount':amount,'reference':reference})


def borrow(connection, state, amount, now):
    sid=state['settlement']['settlement_id']
    if type(amount) is not int or amount<rule('loan_min_amount'):
        raise ValueError('Borrow at least 50 whole Credits.')
    existing=loans(connection,sid)
    if any(row['status']=='liquidating' for row in existing):
        raise ValueError('Repay the liquidating debt before borrowing again.')
    limit=math.floor(value(connection,state)*rule('loan_max_pct_settlement_value')/100)
    if principal(connection,sid)+amount>limit:
        raise ValueError('The loan would exceed 35% of settlement value.')
    rate=health(connection,state['season']['season_id'])['loan_rate']/100
    lid=connection.execute('''INSERT INTO bank_loans(season_id,settlement_id,original_principal,outstanding_balance,daily_rate,opened_at,interest_processed_at,status)
        VALUES (?,?,?,?,?,?,?,'active')''',(state['season']['season_id'],sid,amount,amount,rate,now,now)).lastrowid
    transfer(connection,state,amount,now,'loan_opened',f'loan:{lid}',{'loan_id':lid})
    return lid


def repay(connection, state, lid, amount, now):
    sid=state['settlement']['settlement_id']
    loan=next((row for row in loans(connection,sid) if row['loan_id']==lid),None)
    if not loan:
        raise ValueError('Choose one of your outstanding loans.')
    available=state['resources']['credits']-state.get('reserved',{}).get('credits',0)
    if type(amount) is not int or amount<=0 or amount>min(available,loan['outstanding_balance']):
        raise ValueError('Choose an affordable repayment no larger than the debt.')
    paid=connection.execute("SELECT coalesce(sum(json_extract(transaction_data,'$.principal_paid')),0) FROM credit_transactions WHERE settlement_id=? AND transaction_type='loan_repayment' AND json_extract(transaction_data,'$.loan_id')=?",(sid,lid)).fetchone()[0]
    remaining_principal=max(0,loan['original_principal']-paid)
    principal_paid=max(0,amount-max(0,loan['outstanding_balance']-remaining_principal))
    remaining=loan['outstanding_balance']-amount
    transfer(connection,state,-amount,now,'loan_repayment',f'loan:{lid}:repay:{now}',{'loan_id':lid,'principal_paid':principal_paid})
    connection.execute('UPDATE bank_loans SET outstanding_balance=?,status=?,closed_at=? WHERE loan_id=?',
                       (remaining,'repaid' if remaining==0 else loan['status'],now if remaining==0 else None,lid))


def invest(connection, state, amount, days, now):
    terms={int(rule('investment_term_'+key)):key for key in ('short','medium','long')}
    if days not in terms or type(amount) is not int or amount<=0:
        raise ValueError('Choose a positive whole amount and a 3, 7 or 14 day term.')
    sid=state['settlement']['settlement_id']
    available=state['resources']['credits']-state.get('reserved',{}).get('credits',0)-principal(connection,sid)
    if amount>available:
        raise ValueError('Borrowed or reserved Credits cannot fund an investment.')
    pressure=health(connection,state['season']['season_id'])['pressure']
    rate=max(0,rule('investment_return_'+terms[days])-rule('bank_investment_penalty_max')*pressure)/100
    iid=connection.execute('''INSERT INTO bank_investments(season_id,settlement_id,principal,daily_rate,opened_at,matures_at,interest_processed_at,status,terms_data)
        VALUES (?,?,?,?,?,?,?,'active',?)''',(state['season']['season_id'],sid,amount,rate,now,now+days*86400,now,json.dumps({'days':days,'fraction':0}))).lastrowid
    transfer(connection,state,-amount,now,'investment_opened',f'investment:{iid}',{'investment_id':iid})
    return iid


def withdraw(connection, state, iid, now, *, settled=False):
    row=next((r for r in investments(connection,state['settlement']['settlement_id']) if r['investment_id']==iid),None)
    if not row:
        raise ValueError('Choose one of your active investments.')
    matured=now>=row['matures_at']
    payment=row['principal']+(row['accrued_interest'] if matured or settled else 0)
    status='settled' if settled else 'matured' if matured else 'withdrawn'
    transfer(connection,state,payment,now,'investment_'+status,f'investment:{iid}:close',{'investment_id':iid})
    connection.execute('UPDATE bank_investments SET status=?,closed_at=? WHERE investment_id=?',(status,now,iid))


def accrue(connection, state, now):
    """Accrue at a simulation boundary, never against the wall clock on reads.

    Loan rounding is upward to whole Credits per UTC daily interval. Investment
    fractions carry forward, avoiding a benefit from repeated refreshes.
    """
    sid=state['settlement']['settlement_id']
    for loan in loans(connection,sid):
        if loan['status']=='settled':continue
        boundary=now//86400*86400
        start=loan['interest_processed_at']
        if boundary<=start:
            continue
        cap=loan['original_principal']*2
        balance=loan['outstanding_balance']
        while start<boundary:
            stop=min(boundary,(start//86400+1)*86400)
            balance=min(cap,balance+math.ceil(balance*loan['daily_rate']*(stop-start)/86400-1e-12))
            start=stop
        status='liquidating' if balance>=cap else loan['status']
        connection.execute('UPDATE bank_loans SET outstanding_balance=?,interest_processed_at=?,status=? WHERE loan_id=?',(balance,boundary,status,loan['loan_id']))
        from game.simulation import _event
        _event(connection,state,'bank_interest',boundary,dict(loan_id=loan['loan_id'],before=loan['outstanding_balance'],after=balance))
    for row in investments(connection,sid):
        stop=min(now,row['matures_at']);start=row['interest_processed_at']
        if stop>start:
            terms=json.loads(row['terms_data'])
            earned=row['principal']*row['daily_rate']*(stop-start)/86400+terms.get('fraction',0)
            whole=math.floor(earned+1e-10);terms['fraction']=max(0,earned-whole)
            connection.execute('UPDATE bank_investments SET accrued_interest=accrued_interest+?,interest_processed_at=?,terms_data=? WHERE investment_id=?',(whole,stop,json.dumps(terms),row['investment_id']))
        if now>=row['matures_at']:
            withdraw(connection,state,row['investment_id'],row['matures_at'])


def shift_clock(connection, state, seconds):
    sid=state['settlement']['settlement_id']
    connection.execute("UPDATE bank_loans SET interest_processed_at=interest_processed_at+? WHERE settlement_id=? AND status IN ('active','liquidating')",(seconds,sid))
    connection.execute("UPDATE bank_investments SET interest_processed_at=interest_processed_at+?,matures_at=matures_at+? WHERE settlement_id=? AND status='active'",(seconds,seconds,sid))


def liquidate(connection, state, now):
    """Repay with cash first, then sell assets in the approved fixed order."""
    from game.settlement import read_state
    from game.simulation import _event
    sid=state['settlement']['settlement_id']
    affected=[r for r in loans(connection,sid) if r['status']=='liquidating']
    if not affected:return
    from game.trading import finish
    from game.market import close_listing
    for row in connection.execute("SELECT DISTINCT trade_proposal_id FROM resource_reservations WHERE settlement_id=? AND released_at IS NULL AND trade_proposal_id IS NOT NULL",(sid,)).fetchall():
        finish(connection,row[0],'cancelled',now)
    for row in connection.execute("SELECT listing_id FROM market_listings WHERE seller_settlement_id=? AND status='open'",(sid,)).fetchall():
        close_listing(connection,row[0],now)

    def pay():
        current=read_state(connection)
        for loan in loans(connection,sid):
            if loan['status']!='liquidating':continue
            amount=min(current['resources']['credits'],loan['outstanding_balance'])
            if amount:repay(connection,current,loan['loan_id'],amount,now);current=read_state(connection)
        return any(r['status']=='liquidating' for r in loans(connection,sid))

    def sale(kind, identity, price):
        price=max(0,math.floor(price))
        transfer(connection,state,price,now,'liquidation_sale',f'liquidation:{sid}:{kind}:{identity}:{now}',{'asset_type':kind,'asset_id':identity})
        _event(connection,state,'bank_liquidation_sale',now,{'asset_type':kind,'asset_id':identity,'credits':price})

    if not pay():return
    current=read_state(connection)
    for unit in current['units']:
        if unit['status'] not in ('available','repairing') or unit['current_hp']<=0:continue
        definition=current['config']['units'][unit['unit_type']]
        price=(definition['metal']*2+definition['electronics']*5)*unit['current_hp']/definition['hp']
        connection.execute("UPDATE settlement_jobs SET status='cancelled',pause_reason='Bank liquidation' WHERE target_unit_id=? AND status IN ('active','paused','queued')",(unit['unit_id'],))
        connection.execute("UPDATE military_units SET status='destroyed',current_hp=0,destroyed_at=? WHERE unit_id=?",(now,unit['unit_id']))
        sale('drone',unit['unit_id'],price)
        if not pay():return
    for stock in current['inventory']:
        if not stock['quantity']:continue
        definition=current['config']['units'][stock['unit_type']]
        needed=sum(r['outstanding_balance'] for r in loans(connection,sid) if r['status']=='liquidating')
        unit_value=definition['metal']*2+definition['electronics']*5
        quantity=min(stock['quantity'],math.ceil(needed/unit_value))
        connection.execute('UPDATE military_inventory SET quantity=quantity-?,updated_at=? WHERE inventory_id=?',(quantity,now,stock['inventory_id']))
        sale('ammunition',stock['inventory_id'],quantity*unit_value)
        if not pay():return
    for investment in investments(connection,sid):
        withdraw(connection,read_state(connection),investment['investment_id'],now)
        _event(connection,state,'bank_liquidation_investment',now,{'investment_id':investment['investment_id']})
        if not pay():return
    for resource in ('electronics','metal','scrap','food','water'):
        current=read_state(connection)
        needed=sum(r['outstanding_balance'] for r in loans(connection,sid) if r['status']=='liquidating')
        valuation=settings()['Scoring'][f'settlement_{resource}_value']
        quantity=min(current['resources'][resource],math.ceil(needed/valuation))
        if math.floor(quantity*valuation)<=0:continue
        connection.execute(f'UPDATE settlement_resources SET {resource}={resource}-?,updated_at=? WHERE settlement_id=?',(quantity,now,sid))
        sale('resource',resource,quantity*valuation)
        if not pay():return
    from game.ruins import invested,release
    from game.buildings import spec
    for building in read_state(connection)['buildings']:
        if building['building_type']=='town_hall' or building['status'] not in ('active','upgrading','construction'):continue
        current=read_state(connection);costs,_=invested(current,building)
        price=buildings_value({**current,'buildings':[building]})
        release(connection,sid,building['building_id'],now)
        connection.execute("UPDATE buildings SET status='cleared',current_hp=0,cleared_at=? WHERE building_id=?",(now,building['building_id']))
        sale('building',building['building_id'],price)
        if not pay():break
    from game.population import rebalance
    from game.consequences import replace_admin
    replace_admin(connection,read_state(connection),now)
    rebalance(connection,read_state(connection),now)


def finish(connection, state, now):
    """Close financial clocks at season end; retain unpaid debt in final Wealth."""
    if not state.get('expansion'):return
    from game.settlement import read_state
    sid=state['settlement']['settlement_id']
    for investment in investments(connection,sid):
        withdraw(connection,read_state(connection),investment['investment_id'],now,settled=True)
    for loan in loans(connection,sid):
        current=read_state(connection)
        available=max(0,current['resources']['credits']-current.get('reserved',{}).get('credits',0))
        amount=min(loan['outstanding_balance'],available)
        if amount:repay(connection,current,loan['loan_id'],amount,now)
    connection.execute("UPDATE bank_loans SET status='settled',closed_at=? WHERE settlement_id=? AND status IN ('active','liquidating')",(now,sid))

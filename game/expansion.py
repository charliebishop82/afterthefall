"""Season opt-in and the expansion's simulation-boundary coordination."""
import json
from pathlib import Path
from functools import lru_cache
from game.settlement import account_scope, read_state


@lru_cache(maxsize=1)
def config():
    return json.loads((Path(__file__).resolve().parents[1]/'config/expansion_v1.json').read_text(encoding='utf-8'))


def enabled(connection, season):
    return connection.execute("SELECT 1 FROM game_events WHERE season_id=? AND event_type='expansion_enabled' LIMIT 1",(season,)).fetchone() is not None


def fund(connection, state, now):
    """One per-player reserve contribution, also used for late season joins."""
    sid=state['settlement']['settlement_id'];season=state['season']['season_id']
    if connection.execute("SELECT 1 FROM game_events WHERE settlement_id=? AND event_type='bank_reserve_funded'",(sid,)).fetchone():return
    amount=config()['settings']['Economy Diplomacy']['bank_initial_reserve_per_player']
    connection.execute('UPDATE season_bank SET credits=credits+?,updated_at=? WHERE season_id=?',(amount,now,season))
    balance=connection.execute('SELECT credits FROM season_bank WHERE season_id=?',(season,)).fetchone()[0]
    connection.execute("INSERT INTO credit_transactions(season_id,transfer_ref,transaction_type,amount,balance_after,occurred_at) VALUES (?,?,'bank_initial_reserve',?,?,?)",(season,f'bank-reserve:{sid}',amount,balance,now))
    from game.simulation import _event
    _event(connection,state,'bank_reserve_funded',now,{'credits':amount})


def enable(connection, state, now):
    if enabled(connection,state['season']['season_id']):return
    from game.trading import player_state
    for row in connection.execute('SELECT settlement_id FROM settlements WHERE season_id=?',(state['season']['season_id'],)).fetchall():
        player_state(connection,row[0],now)
    from game.consequences import enable as citizen_enable
    citizen_enable(connection,read_state(connection),now)
    from game.simulation import _event
    _event(connection,state,'expansion_enabled',now,{'version':config()['version']})
    for row in connection.execute('SELECT account_id FROM settlements WHERE season_id=?',(state['season']['season_id'],)).fetchall():
        with account_scope(row[0]):fund(connection,read_state(connection),now)


def overlay(connection, season, original):
    active=enabled(connection,season)
    if not active or 'buildings' not in original:return original,False
    # These catalogues contain JSON values only. A JSON round trip makes an
    # independent snapshot much faster than recursively copying every field.
    # Copy the overlay too: a caller must never mutate the cached source rules.
    result=json.loads(json.dumps({**original,'buildings':{
        **original['buildings'],**config()['buildings']}}))
    renewable=config().get('renewable_scrap')
    if renewable and renewable['building'] in result['buildings']:
        for level,output in zip(result['buildings'][renewable['building']]['levels'],renewable['output_per_worker_hour']):
            level['scrap_output']=output
    return result,True


def boundary(connection, state, now):
    if not state.get('expansion') or state['settlement']['status']!='active' or state['season']['status'] not in ('active','finalizing'):
        return False
    from game import banking,capture
    before=connection.total_changes
    capture.daily(connection,state,now)
    if connection.total_changes!=before:state=read_state(connection)
    captured=connection.total_changes
    banking.accrue(connection,state,now)
    if connection.total_changes!=captured:state=read_state(connection)
    banking.liquidate(connection,state,now)
    return connection.total_changes!=before


def transact(path, action, now, *, amount=None, days=None, loan_id=None, investment_id=None):
    from game import banking,social
    if action not in ('enable','borrow','repay','invest','withdraw'):
        raise ValueError('Unknown Bank action.')
    if action in ('borrow','invest'):refresh(path,now)
    with social.transaction(path,now,new=action in ('enable','borrow','invest')) as (connection,state):
        if action=='enable':enable(connection,state,now);return
        if not state.get('expansion'):raise ValueError('Enable the expansion first.')
        if action=='borrow':return banking.borrow(connection,state,amount,now)
        if action=='repay':return banking.repay(connection,state,loan_id,amount,now)
        if action=='invest':return banking.invest(connection,state,amount,days,now)
        return banking.withdraw(connection,state,investment_id,now)


def refresh(path, now):
    """Bring public ranking participants to one time before rendering totals."""
    from contextlib import closing
    import sqlite3
    from database.create_database import connect_database
    from game.settlement import CURRENT_ACCOUNT
    from game.trading import player_state
    with closing(connect_database(path)) as connection,connection:
        connection.row_factory=sqlite3.Row
        row=connection.execute('''SELECT s.season_id FROM settlements s WHERE s.account_id=?
            AND EXISTS(SELECT 1 FROM game_events e WHERE e.season_id=s.season_id AND e.event_type='expansion_enabled')
            ORDER BY s.season_id DESC LIMIT 1''',(CURRENT_ACCOUNT.get(),)).fetchone()
        if not row:return
        connection.execute('BEGIN IMMEDIATE')
        for player in connection.execute('''SELECT s.settlement_id FROM settlements s
            JOIN accounts a USING(account_id) WHERE s.season_id=? AND a.is_active=1
            AND (s.status<>'active' OR s.simulation_processed_at<?)
            ORDER BY s.settlement_id''',(row[0],now)).fetchall():
            player_state(connection,player[0],now)

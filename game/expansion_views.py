"""Account controls for the opt-in expansion and public score totals."""
from contextlib import closing
from html import escape
from datetime import datetime, timezone
import sqlite3
from database.create_database import connect_database
from game import banking,scoring,social
from game.settlement import account_scope,read_state


def scores(connection, state):
    players=[]
    rows=connection.execute('SELECT account_id FROM settlements WHERE season_id=? ORDER BY settlement_id',(state['season']['season_id'],)).fetchall()
    for row in rows:
        with account_scope(row[0]):
            current=read_state(connection);sid=current['settlement']['settlement_id']
            result=scoring.totals(current,banking.loans(connection,sid),banking.investments(connection,sid))
            players.append(dict(result,settlement_id=sid,name=current['settlement']['settlement_name']))
    return scoring.rank(players)


def panel(path, state, token, now):
    if not state.get('expansion'):
        return '<section class="production-panel" id="bank"><h2>Next expansion</h2><p>Enable allied defense, citizen capture, Credit raids and Vaults, scoring and banking for this season. Existing progress is kept; the new rules start now.</p>'+social.form(token,'bank','enable','<button>Enable expansion for this season</button>')+'</form></section>'
    sid=state['settlement']['settlement_id']
    with closing(connect_database(path)) as connection:
        connection.row_factory=sqlite3.Row
        outstanding=banking.loans(connection,sid);active=banking.investments(connection,sid)
        health=banking.health(connection,state['season']['season_id']);value=banking.value(connection,state)
        rows=scores(connection,state)
    html='<section class="production-panel" id="bank"><h2>Bank</h2>'
    html+=f'<p>Settlement value: {value:.0f} Credits. Reserve: {health["reserve"]} Credits. Loan rate for new loans: {health["loan_rate"]:g}% daily. Current debt morale modifier: {state.get("debt_morale_modifier",0):.1f}.</p>'
    from game.vaults import allocations
    protection=allocations(state)
    html+=f'<p>Credits protected in powered Vaults: {sum(a["protected"] for a in protection.values())}. Credits allocated to Vaults: {sum(a["allocated"] for a in protection.values())}.</p>'
    html+='<p>Loans are capped at 35% of settlement value. Interest is charged at midnight UTC. Early investment withdrawal returns principal and forfeits interest. Borrowed Credits cannot be invested. Insolvency sells assets to repay debt; the Town Hall and citizens are protected from liquidation.</p>'
    amount='<label>Credits <input name="amount" type="number" min="1" step="1" required></label>'
    html+=social.form(token,'bank','borrow',amount+'<button>Borrow Credits</button>','Borrow Credits')+'</form>'
    html+=social.form(token,'bank','invest',amount+'<label>Term <select name="days"><option value="3">3 days</option><option value="7">7 days</option><option value="14">14 days</option></select></label><button>Invest Credits</button>','Invest Credits')+'</form>'
    for row in outstanding:
        html+=f'<p>Loan #{row["loan_id"]}: {row["outstanding_balance"]} Credits outstanding · {row["daily_rate"]*100:g}% daily · {row["status"]}.</p>'
        html+=social.form(token,'bank','repay',social.hidden('loan_id',row['loan_id'])+amount+'<button>Repay loan</button>',f'Repay loan {row["loan_id"]}')+'</form>'
    for row in active:
        maturity=datetime.fromtimestamp(row['matures_at'],timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        html+=f'<p>Investment #{row["investment_id"]}: {row["principal"]} Credits principal + {row["accrued_interest"]} earned · {row["daily_rate"]*100:g}% daily · matures {maturity}.</p>'
        html+=social.form(token,'bank','withdraw',social.hidden('investment_id',row['investment_id'])+'<button>Withdraw investment early</button>',f'Withdraw investment {row["investment_id"]}')+'</form>'
    html+='</section><section class="production-panel" id="rankings"><h2>Season rankings</h2><p>Equal category weights; overall scores are relative to each category leader. Exact ties share rank. Population and development details remain private.</p><table><thead><tr><th>Rank</th><th>Settlement</th><th>Overall</th><th>Population</th><th>Military</th><th>Wealth</th><th>Development</th></tr></thead><tbody>'
    for row in rows:
        html+=f'<tr><td>{row["rank"]}</td><td>{escape(row["name"])}</td>'+''.join(f'<td id="score-{row["settlement_id"]}-{c}">{row[c]:.2f}</td>' for c in ('overall','population','military','wealth','development'))+'</tr>'
    return html+'</tbody></table></section>'

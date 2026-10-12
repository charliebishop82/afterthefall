"""Admin bot registry and retained decision history; gameplay goes through HTTP."""
from contextlib import closing
from html import escape
import json
import secrets
import sqlite3
from database.create_database import connect_database
from game import accounts,admin,lobby
from datetime import datetime,timezone


def prepare(path):
    with closing(connect_database(path)) as c,c:
        c.execute('''CREATE TABLE IF NOT EXISTS bot_controllers(
            account_id INTEGER PRIMARY KEY REFERENCES accounts(account_id),
            state TEXT NOT NULL CHECK(state IN ('paused','running')),seed INTEGER NOT NULL,
            interval_seconds INTEGER NOT NULL DEFAULT 30 CHECK(interval_seconds>=10),
            next_at INTEGER NOT NULL,last_at INTEGER,steps INTEGER NOT NULL DEFAULT 0,
            lease_until INTEGER NOT NULL DEFAULT 0,created_by INTEGER REFERENCES accounts(account_id)) STRICT''')
        c.execute('''CREATE TABLE IF NOT EXISTS bot_decisions(
            decision_id INTEGER PRIMARY KEY,account_id INTEGER NOT NULL REFERENCES accounts(account_id),
            occurred_at INTEGER NOT NULL,reason TEXT NOT NULL,route TEXT,parameters TEXT NOT NULL,
            status INTEGER,request_id TEXT,error TEXT) STRICT''')

        columns={r[1] for r in c.execute('PRAGMA table_info(bot_controllers)')}
        if 'personality' not in columns:
            c.execute("ALTER TABLE bot_controllers ADD COLUMN personality TEXT NOT NULL DEFAULT 'balanced'")
        c.execute('''CREATE TABLE IF NOT EXISTS bot_traces(
            trace_id INTEGER PRIMARY KEY,account_id INTEGER NOT NULL REFERENCES accounts(account_id),
            occurred_at INTEGER NOT NULL,timestamp_utc TEXT NOT NULL,phase TEXT NOT NULL,payload TEXT NOT NULL) STRICT''')
        c.execute('CREATE INDEX IF NOT EXISTS bot_trace_account ON bot_traces(account_id,trace_id)')


def trace(path,aid,phase,payload):
    from time import time
    stamp=datetime.now(timezone.utc).isoformat(timespec='milliseconds')
    with closing(connect_database(path)) as c,c:
        c.execute('PRAGMA busy_timeout=1000')
        c.execute('INSERT INTO bot_traces(account_id,occurred_at,timestamp_utc,phase,payload) VALUES (?,?,?,?,?)',
                  (aid,int(time()),stamp,phase,json.dumps(payload,allow_nan=False)))


def create(path,actor,username,name,now,personality='balanced'):
    # One atomic normal account + membership transaction; no credentials retained.
    from game.lobby import enrollment_open,join_member
    if personality not in ('balanced','builder','scavenger','aggressive','defensive'):raise ValueError('Choose a supported bot personality.')
    with closing(connect_database(path)) as c,c:
        c.row_factory=sqlite3.Row;c.execute('BEGIN IMMEDIATE');admin.require(c,actor)
        name=name.strip()
        if not 1<=len(name)<=40 or any(ord(ch)<32 for ch in name):raise ValueError('Choose a settlement name of 1–40 characters.')
        started=c.execute('SELECT status FROM playtest_control WHERE singleton=1').fetchone()[0]=='started'
        season=c.execute('SELECT * FROM seasons ORDER BY season_id DESC LIMIT 1').fetchone()
        if started and not enrollment_open(season,now):raise ValueError('Season enrollment is closed.')
        aid=accounts.register_in_transaction(c,username,secrets.token_urlsafe(32),now)
        try:c.execute('INSERT INTO playtest_members VALUES (?,?,?)',(aid,name,now))
        except sqlite3.IntegrityError:raise ValueError('That settlement name is already reserved.') from None
        c.execute("INSERT INTO bot_controllers(account_id,state,seed,next_at,created_by) VALUES (?,'paused',?,?,?)",(aid,secrets.randbelow(2**31),now,actor))
        c.execute('UPDATE bot_controllers SET personality=? WHERE account_id=?',(personality,aid))
        if started and season['status']=='active':join_member(c,dict(account_id=aid,settlement_name=name),now)
        admin.audit(c,actor,'bot_create','account',aid,now,'Create normal economy bot',{},dict(controller='paused',normal_start=True,personality=personality),season['season_id'] if season else None)
        return aid


def control(path,actor,aid,action,now):
    if action not in ('start','pause'):raise ValueError('Choose Start or Pause.')
    with closing(connect_database(path)) as c,c:
        c.row_factory=sqlite3.Row;c.execute('BEGIN IMMEDIATE');admin.require(c,actor)
        before=c.execute('SELECT * FROM bot_controllers WHERE account_id=?',(aid,)).fetchone()
        if not before:raise ValueError('Bot not found.')
        state='running' if action=='start' else 'paused'
        c.execute('UPDATE bot_controllers SET state=?,next_at=? WHERE account_id=?',(state,now,aid))
        admin.audit(c,actor,'bot_'+action,'account',aid,now,'Operator bot controller change',dict(state=before['state']),dict(state=state))


def claim(path,now):
    with closing(connect_database(path)) as c,c:
        c.row_factory=sqlite3.Row;c.execute('BEGIN IMMEDIATE')
        row=c.execute("SELECT b.* FROM bot_controllers b JOIN accounts a USING(account_id) WHERE b.state='running' AND a.is_active=1 AND b.next_at<=? AND b.lease_until<=? ORDER BY b.next_at,b.account_id LIMIT 1",(now,now)).fetchone()
        if not row:return None
        c.execute('UPDATE bot_controllers SET lease_until=?,next_at=? WHERE account_id=?',(now+120,now+row['interval_seconds'],row['account_id']))
        return dict(row)


def record(path,aid,now,decision,status=None,request_id=None,error=None):
    with closing(connect_database(path)) as c,c:
        c.execute('INSERT INTO bot_decisions(account_id,occurred_at,reason,route,parameters,status,request_id,error) VALUES (?,?,?,?,?,?,?,?)',
                  (aid,now,decision['reason'],decision.get('route'),json.dumps(decision.get('form',{})),status,request_id,error))
        c.execute('UPDATE bot_controllers SET last_at=?,steps=steps+1,lease_until=0 WHERE account_id=?',(now,aid))
        # Retain decision history for later analysis; no automatic pruning.


def suggested_bot_name(usernames,names):
    index=1
    while f'bot_{index}' in usernames or f'Bot {index}' in names:index+=1
    return f'bot_{index}',f'Bot {index}'


def panel(path,token):
    with closing(connect_database(path)) as c:
        c.row_factory=sqlite3.Row
        rows=c.execute('''SELECT b.*,a.username,(SELECT max(settlement_id) FROM settlements s WHERE s.account_id=b.account_id) AS settlement_id FROM bot_controllers b JOIN accounts a USING(account_id) ORDER BY account_id''').fetchall()
        decisions=c.execute('SELECT * FROM bot_decisions ORDER BY decision_id DESC LIMIT 100').fetchall()
        suggestion,suggested_settlement=suggested_bot_name(
            {r[0] for r in c.execute('SELECT username FROM accounts')},
            {r[0] for r in c.execute('SELECT settlement_name FROM playtest_members')})
    hidden=f'<input type="hidden" name="token" value="{escape(token,quote=True)}">'
    html='<h2>Computer players</h2><p>Controllers use ordinary player requests. Start the separate runner to execute decisions. Pausing a controller stops its next decision; an in-flight action may finish. Settlement time continues normally.</p>'
    html+=f'<section class="operator-card"><h3>Create a normal bot account</h3><form method="post" action="/bots">'+hidden+f'<input type="hidden" name="action" value="create"><label>Username <input name="username" pattern="[A-Za-z][A-Za-z0-9_]{{2,23}}" value="{suggestion}" title="3–24 letters, numbers or underscores; start with a letter. Example: bot_2. No spaces or hyphens." aria-describedby="bot-username-help" required maxlength="24"></label><small id="bot-username-help">Username: 3–24 letters, numbers or underscores; start with a letter. Use bot_2, not Bot 2 or bot-2. Capital letters are accepted and saved lowercase.</small><label>Settlement name <input name="name" value="{suggested_settlement}" required maxlength="40"></label><label>Personality <select name="personality"><option value="balanced">Balanced</option><option value="builder">Builder</option><option value="scavenger">Scavenger</option><option value="aggressive">Aggressive</option><option value="defensive">Defensive</option></select></label><button>Create paused bot</button></form></section>'
    for row in rows:
        action='pause' if row['state']=='running' else 'start'
        html+=f'<section class="operator-card"><h3>{escape(row["username"])} · {row["state"]} · {escape(row["personality"])}</h3><p>{row["steps"]} decisions · interval {row["interval_seconds"]}s · last decision UTC Unix time: {row["last_at"] or "none"}</p><form method="post" action="/bots">{hidden}<input type="hidden" name="action" value="{action}"><input type="hidden" name="target" value="{row["account_id"]}"><button>{action.title()} controller</button></form>'
        if row['settlement_id']:html+=f'<a href="/players/{row["settlement_id"]}">Inspect map & assignments</a> · <a href="/player-logs?account={row["account_id"]}">Player request log</a>'
        else:html+='<p>Waiting for season launch/resume.</p>'
        html+=f' · <a href="/bot-traces?account={row["account_id"]}">Decision traces / export</a></section>'
    html+='<section class="operator-card"><h3>Behavior coverage</h3><p>Implemented: Administrator, worker/builder staffing, safe scavenging, economy infrastructure, Town Hall and needs-based upgrades; military factories/storage and finite equipment batches, guards/patrols, paid building repairs, war declarations and raids; urgent market purchases, construction/upgrade supply purchases and surplus sales; personality-weighted citizen expeditions and needs-based recalls; five personalities.</p><p>Not yet automated: rations, private trades, banking, diplomacy, capture integration/expulsion and drone servicing. Trade, banking, diplomacy, ration policies, capture integration/expulsion and drone servicing remain deferred.</p></section>'
    html+='<h3>Recent bot decisions — latest 100</h3><div class="table-scroll"><table><thead><tr><th>UTC Unix time</th><th>Account</th><th>Decision</th><th>Result</th><th>Details</th></tr></thead><tbody>'
    for row in decisions:
        html+=f'<tr><td>{row["occurred_at"]}</td><td>#{row["account_id"]}</td><td>{escape(row["reason"])}</td><td>{row["status"] or "Wait"}<br>{escape(row["error"] or "")}</td><td><details><summary>Request / parameters</summary><pre>{escape(row["route"] or "No action")}\n{escape(row["parameters"])}\nRequest ID: {escape(row["request_id"] or "—")}</pre></details></td></tr>'
    return html+'</tbody></table></div>'

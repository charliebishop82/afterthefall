"""Bilateral peace, non-aggression, trade and defense treaties; war is unilateral."""
from contextlib import closing
from html import escape
import sqlite3
from database.create_database import connect_database
from game import social
from game.combat import settings
from game.settlement import read_state

TYPES = {'peace': 'Peace', 'non_aggression': 'Non-aggression', 'trade_agreement': 'Trade agreement'}
BLOCKING = ('peace', 'non_aggression')
DEFENSE_TYPES={'mutual_defense':'Mutual defense','full_defense':'Full defense'}
TYPES.update(DEFENSE_TYPES)


def rule(key):
    return settings()['Economy Diplomacy'][key]


def synchronize(c, state, now):
    from game.admin_controls import table_exists
    if table_exists(c, 'admin_timer_freezes'):
        season = state['season']; limit = min(now, season['ends_at'])
        if season['status']=='paused':return
        c.execute("""UPDATE treaties SET status='expired' WHERE season_id=? AND status='proposed' AND expires_at<=?
            AND NOT EXISTS(SELECT 1 FROM admin_timer_freezes f WHERE f.kind='treaty' AND f.target_id=treaties.treaty_id)""", (season['season_id'], limit))
        if now>=season['ends_at']:
            c.execute("UPDATE treaties SET status='expired' WHERE season_id=? AND status='proposed'", (season['season_id'],))
        return
    season = state['season']; limit = min(now, season['ends_at'])
    if season['status']=='paused':limit=min(limit,season['paused_at'] or limit)
    c.execute("UPDATE treaties SET status='expired' WHERE season_id=? AND status='proposed' AND expires_at<=?",
              (season['season_id'], limit))
    if season['status']!='paused' and now >= season['ends_at']:
        c.execute("UPDATE treaties SET status='expired' WHERE season_id=? AND status='proposed'", (season['season_id'],))


def war_cooldown(c, a, b, now):
    a, b = sorted((a, b))
    from game.admin_controls import treaty_offset
    rows = c.execute("SELECT treaty_id,accepted_at,cancelled_at FROM treaties WHERE settlement_a_id=? AND settlement_b_id=? AND treaty_type='peace' AND accepted_at IS NOT NULL", (a, b)).fetchall()
    return any(max(row['accepted_at']+treaty_offset(c,row['treaty_id']),
                   row['cancelled_at']+treaty_offset(c,row['treaty_id'],'cancelled_at') if row['cancelled_at'] is not None else 0)
               + int(rule('war_peace_cooldown')*3600) > now for row in rows)


def transact(path, action, now, *, target_id=None, treaty_type=None, treaty_id=None):
    if action not in ('propose', 'accept', 'reject', 'cancel'):
        raise ValueError('Unknown diplomacy action.')
    with social.transaction(path, now, new=action in ('propose', 'accept')) as (c, state):
        synchronize(c, state, now)
        sid = state['settlement']['settlement_id']; season = state['season']['season_id']
        row = None
        if action != 'propose':
            row = c.execute('SELECT * FROM treaties WHERE treaty_id=? AND season_id=?', (treaty_id, season)).fetchone()
            if not row or sid not in (row['settlement_a_id'], row['settlement_b_id']) or row['treaty_type'] not in TYPES:
                raise ValueError('Choose one of your treaties.')
            target_id = row['settlement_b_id'] if row['settlement_a_id'] == sid else row['settlement_a_id']
            treaty_type = row['treaty_type']
        other = social.other(c, state, target_id, now)
        state = read_state(c)
        from game.trading import eligible
        eligible(c,state,now,transactional=action in ('propose','accept'))
        synchronize(c, state, now)
        a, b = sorted((sid, target_id))
        if action == 'propose':
            if treaty_type in DEFENSE_TYPES and not state.get('expansion'):raise ValueError('Enable the expansion before proposing defense treaties.')
            if treaty_type not in TYPES:
                raise ValueError('Choose an available treaty type.')
            if c.execute("SELECT 1 FROM treaties WHERE settlement_a_id=? AND settlement_b_id=? AND treaty_type=? AND status IN ('active','proposed')", (a,b,treaty_type)).fetchone():
                raise ValueError('This treaty is already active or proposed.')
            from game.admin_controls import treaty_offset
            cancelled = c.execute("SELECT treaty_id,cancelled_at FROM treaties WHERE settlement_a_id=? AND settlement_b_id=? AND treaty_type=? AND status='cancelled'", (a,b,treaty_type)).fetchall()
            if any(row['cancelled_at']+treaty_offset(c,row['treaty_id'],'cancelled_at')+int(rule('treaty_cancel_cooldown')*3600)>now for row in cancelled):
                raise ValueError('Wait twelve hours before proposing this cancelled treaty again.')
            treaty_id = c.execute('''INSERT INTO treaties(season_id,settlement_a_id,settlement_b_id,treaty_type,status,proposer_settlement_id,proposed_at,expires_at)
                VALUES (?,?,?,?,'proposed',?,?,?)''', (season,a,b,treaty_type,sid,now,now+int(rule('treaty_proposal_expiry')*3600))).lastrowid
        else:
            row = c.execute('SELECT * FROM treaties WHERE treaty_id=?', (treaty_id,)).fetchone()
            if action in ('accept', 'reject'):
                if row['status'] != 'proposed' or row['proposer_settlement_id'] == sid:
                    raise ValueError('Only the recipient can accept or reject a pending proposal.')
                status = 'active' if action == 'accept' else 'rejected'
                c.execute('UPDATE treaties SET status=?,accepted_at=?,effective_at=?,expires_at=NULL WHERE treaty_id=?',
                          (status, now if action=='accept' else None, now if action=='accept' else None, treaty_id))
                if action == 'accept' and treaty_type in BLOCKING:
                    from game.combat import cancel
                    for attack in c.execute("SELECT * FROM attacks WHERE status='in_flight' AND ((attacker_settlement_id=? AND defender_settlement_id=?) OR (attacker_settlement_id=? AND defender_settlement_id=?))",(a,b,b,a)).fetchall():
                        cancel(c, attack, now, 'Peace or non-aggression treaty accepted.')
                if action == 'accept' and treaty_type == 'peace':
                    c.execute("UPDATE treaties SET status='cancelled',cancelled_at=?,cooldown_until=? WHERE settlement_a_id=? AND settlement_b_id=? AND treaty_type='war' AND status='active'",(now,now+int(rule('war_peace_cooldown')*3600),a,b))
            else:
                if row['status'] not in ('active','proposed') or (row['status']=='proposed' and row['proposer_settlement_id']!=sid):
                    raise ValueError('Cancel your own proposal or an active treaty.')
                # Workbook separates twelve-hour re-proposal from six-hour peace-to-war.
                hours = rule('war_peace_cooldown') if treaty_type=='peace' else rule('treaty_cancel_cooldown')
                until = now+int(hours*3600) if row['status']=='active' and treaty_type in BLOCKING else None
                c.execute("UPDATE treaties SET status='cancelled',cancelled_at=?,cooldown_until=? WHERE treaty_id=?", (now,until,treaty_id))
        text = f'{TYPES[treaty_type]}: {action} between {state["settlement"]["settlement_name"]} and {other["settlement"]["settlement_name"]}.'
        for owner in (state, other):
            social.notify(c,owner['settlement']['account_id'],season,'diplomacy',text,now,'treaty',treaty_id)
        if action in ('accept','cancel'):
            social.news(c,season,'treaty',text,now)
        from game.simulation import _event
        _event(c,state,'diplomacy_'+action,now,{'treaty_id':treaty_id})
        return treaty_id


def panel(path,state,token,now):
    if state['season']['status']=='paused':now=state['season']['paused_at'] or now
    sid=state['settlement']['settlement_id']; season=state['season']['season_id']
    with closing(connect_database(path)) as c:
        c.row_factory=sqlite3.Row
        rows=c.execute('''SELECT t.*,a.settlement_name AS a_name,b.settlement_name AS b_name FROM treaties t
            JOIN settlements a ON a.settlement_id=t.settlement_a_id JOIN settlements b ON b.settlement_id=t.settlement_b_id
            WHERE t.season_id=? AND (t.settlement_a_id=? OR t.settlement_b_id=?) ORDER BY treaty_id DESC LIMIT 50''',(season,sid,sid)).fetchall()
        people=social.players(c,state)
    html='<section class="production-panel" id="diplomacy"><h2>Diplomacy</h2><p>Peace and non-aggression block attacks and recall inbound raids when accepted. Trade agreements record a trade relationship but do not change pooled-market prices or fees. Proposals expire after 48 hours. Cancelled peace blocks war for 6 hours; cancelled non-aggression blocks hostility for 12 hours. Re-proposing a cancelled treaty requires 12 hours.</p>'
    if people:
        html+=social.form(token,'diplomacy','propose',f'<label>Player <select name="target_id">{social.options(people)}</select></label><label>Treaty <select name="treaty_type">'+''.join(f'<option value="{k}">{v}</option>' for k,v in TYPES.items() if state.get('expansion') or k not in DEFENSE_TYPES)+'</select></label><button>Propose treaty</button></form>','Propose treaty')
    for r in rows:
        status='expired' if r['status']=='proposed' and (now>=r['expires_at'] or now>=state['season']['ends_at']) else r['status']
        html+=f'<div class="building-controls"><p>#{r["treaty_id"]} {escape(r["a_name"])} / {escape(r["b_name"])}: {escape(TYPES.get(r["treaty_type"],r["treaty_type"]))} — {status}.'
        if r['cooldown_until'] and r['cooldown_until']>now:html+=f' Hostility cooldown: {r["cooldown_until"]-now} seconds.'
        html+='</p>'
        actions=() if r['treaty_type'] not in TYPES else ('cancel',) if status=='active' or (status=='proposed' and r['proposer_settlement_id']==sid) else ('accept','reject') if status=='proposed' else ()
        for action in actions:html+=social.form(token,'diplomacy',action,social.hidden('treaty_id',r['treaty_id'])+f'<button>{action.title()} treaty #{r["treaty_id"]}</button></form>')
        html+='</div>'
    return html+'</section>'

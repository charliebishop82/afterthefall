"""Explicit administrator authority and audited account/moderation controls."""
from contextlib import closing
from html import escape
import json
import sqlite3

from database.create_database import connect_database
from game import accounts, communication


def require(c, actor):
    row = c.execute('SELECT * FROM accounts WHERE account_id=? AND is_active=1 AND is_admin=1', (actor,)).fetchone()
    if not row:
        raise PermissionError('Administrator access required.')
    return row


def audit(c, actor, action, kind, target, now, reason, before, after, season=None):
    c.execute('''INSERT INTO admin_actions(admin_account_id,season_id,action_type,target_type,target_id,
        occurred_at,reason,before_values,after_values) VALUES (?,?,?,?,?,?,?,?,?)''',
        (actor, season, action, kind, target, now, reason, json.dumps(before), json.dumps(after)))


def grant(path, username, now):
    """Local operator command only; no web endpoint grants administrator rights."""
    with closing(connect_database(path)) as c, c:
        c.row_factory = sqlite3.Row
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM accounts WHERE username=? AND is_active=1', (username.strip().lower(),)).fetchone()
        if not row:
            raise ValueError('Create an active account first.')
        if row['is_admin']:
            return row['account_id']
        c.execute('UPDATE accounts SET is_admin=1 WHERE account_id=?', (row['account_id'],))
        audit(c, row['account_id'], 'local_admin_grant', 'account', row['account_id'], now,
              'Explicit local operator grant', {'is_admin': 0}, {'is_admin': 1})
        return row['account_id']


def create_operator(path, username, password, now):
    """Explicit local bootstrap; account and audited role creation commit together."""
    import re
    username = username.strip().lower()
    if not re.fullmatch('[a-z][a-z0-9_]{2,23}', username):
        raise ValueError('Use 3–24 letters, numbers or underscores, starting with a letter.')
    if not 12 <= len(password) <= 128:
        raise ValueError('Use a password of 12–128 characters.')
    hashed = accounts.password_hash(password)
    with closing(connect_database(path)) as c, c:
        c.execute('BEGIN IMMEDIATE')
        try:
            aid = c.execute('INSERT INTO accounts(username,password_hash,display_name,created_at,is_admin) VALUES (?,?,?,?,1)',(username,hashed,username,now)).lastrowid
        except sqlite3.IntegrityError:
            raise ValueError('That username is already taken. Use grant-admin for an existing account.') from None
        audit(c, aid, 'local_admin_create', 'account', aid, now, 'Explicit local operator creation', {}, {'is_admin':1,'username':username})
        return aid


def transact(path, actor, action, now, *, target=None, reason='', password='', body='',
             settlement_id=None, field='', value=None, expected=None):
    with closing(connect_database(path)) as c, c:
        c.row_factory = sqlite3.Row
        c.execute('BEGIN IMMEDIATE')
        require(c, actor)
        reason = communication.text(reason, 200)
        from game import admin_controls as controls
        controls.ensure(c)
        if action in controls.CORRECTIONS:
            controls.correct(c, actor, action, settlement_id, target, field, value, expected, now, reason)
            return
        if action in ('pause_season', 'resume_season'):
            controls.season_control(c, actor, action, target, now, reason)
            if action=='resume_season':
                from game.lobby import activate_reserved
                activate_reserved(c,now,target)
            return
        if action in ('suspend', 'reactivate', 'reset_password'):
            row = c.execute('SELECT * FROM accounts WHERE account_id=?', (target,)).fetchone()
            if not row:
                raise ValueError('Choose an existing account.')
            # Prevent administrator lockout and privileged account resets by another admin.
            if row['is_admin']:
                raise ValueError('Use account settings for your own password; administrator accounts cannot be suspended or reset here.')
            if action == 'reset_password':
                if not 12 <= len(password) <= 128:
                    raise ValueError('Use a password of 12–128 characters.')
                c.execute('UPDATE accounts SET password_hash=? WHERE account_id=?', (accounts.password_hash(password), target))
                c.execute('DELETE FROM auth_failures WHERE username=?', (row['username'],))
                before, after = {}, {'password_reset': True, 'sessions_revoked': True}
            else:
                active = int(action == 'reactivate')
                if active == row['is_active']:
                    raise ValueError('Account already has this status.')
                settlements = controls.reactivate(c, target, now) if active else controls.suspend(c, target, now)
                c.execute('UPDATE accounts SET is_active=? WHERE account_id=?', (active, target))
                before, after = {'is_active': row['is_active']}, {'is_active': active}
                after['settlements'] = settlements
            c.execute('DELETE FROM auth_sessions WHERE account_id=?', (target,))
            audit(c, actor, action, 'account', target, now, reason, before, after)
        elif action in ('hide_post', 'restore_post'):
            row = c.execute('SELECT * FROM board_posts WHERE post_id=?', (target,)).fetchone()
            if not row:
                raise ValueError('Choose an existing board post.')
            status = 'hidden' if action == 'hide_post' else 'visible'
            if status == row['moderation_status']:
                raise ValueError('Post already has this status.')
            c.execute('UPDATE board_posts SET moderation_status=?,moderated_by=?,moderated_at=? WHERE post_id=?', (status, actor, now, target))
            audit(c, actor, action, 'board_post', target, now, reason,
                  {'moderation_status': row['moderation_status']}, {'moderation_status': status}, row['season_id'])
        elif action == 'announce':
            season = c.execute("SELECT season_id FROM seasons WHERE status IN ('active','finalizing','paused') ORDER BY season_id DESC LIMIT 1").fetchone()
            if not season:
                raise ValueError('There is no current season to announce to.')
            body = communication.text(body, 200)
            nid = c.execute("INSERT INTO news_events(season_id,event_type,occurred_at,headline) VALUES (?,'admin_announcement',?,?)", (season[0], now, body)).lastrowid
            c.execute("INSERT INTO notifications(account_id,season_id,notification_type,message,created_at) SELECT account_id,?,'admin_announcement',?,? FROM settlements WHERE season_id=?", (season[0], body, now, season[0]))
            audit(c, actor, action, 'news', nid, now, reason, {}, {'headline': body}, season[0])
        else:
            raise ValueError('Unknown admin action.')


def change_password(path, actor, current, password, now):
    with closing(connect_database(path)) as c, c:
        c.row_factory = sqlite3.Row
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT * FROM accounts WHERE account_id=? AND is_active=1', (actor,)).fetchone()
        if not row or not accounts.verify(current, row['password_hash']):
            raise ValueError('Current password is incorrect.')
        if not 12 <= len(password) <= 128:
            raise ValueError('Use a password of 12–128 characters.')
        c.execute('UPDATE accounts SET password_hash=? WHERE account_id=?', (accounts.password_hash(password), actor))
        c.execute('DELETE FROM auth_sessions WHERE account_id=?', (actor,))
        c.execute('DELETE FROM auth_failures WHERE username=?', (row['username'],))


def form(token, action, fields):
    return (f'<form method="post" action="/admin"><input type="hidden" name="token" value="{escape(token, quote=True)}">'
            f'<input type="hidden" name="action" value="{action}">{fields}'
            '<label>Reason <input name="reason" maxlength="200" required></label>'
            f'<button>{escape(action.replace("_", " ").title())}</button></form>')


def panel(path, actor, token):
    with closing(connect_database(path)) as c:
        c.row_factory = sqlite3.Row
        require(c, actor)
        players = c.execute('SELECT account_id,username,is_active,is_admin FROM accounts ORDER BY account_id').fetchall()
        settlements = c.execute('SELECT settlement_id,account_id,settlement_name,season_id,status FROM settlements ORDER BY settlement_id DESC').fetchall()
        posts = c.execute('SELECT p.*,a.username FROM board_posts p JOIN accounts a ON a.account_id=p.author_account_id ORDER BY post_id DESC LIMIT 100').fetchall()
        logs = c.execute('SELECT l.*,a.username FROM admin_actions l JOIN accounts a ON a.account_id=l.admin_account_id ORDER BY admin_action_id DESC LIMIT 100').fetchall()
        from game.admin_controls import controls
        operational = controls(c, token, form)
    html = '<h1>Administration</h1><p>Suspension revokes sessions, freezes the settlement and protects it from attacks. Pending raids involving the account are recalled immediately. Reactivation preserves progress without replaying suspended time.</p><h2>Accounts</h2>'
    for p in players:
        html += f'<section class="production-panel"><h3>{escape(p["username"])}</h3><p>Account #{p["account_id"]} · '+('Active' if p['is_active'] else 'Suspended')+(' · Administrator' if p['is_admin'] else '')+'</p>'
        if not p['is_admin']:
            target = f'<input type="hidden" name="target" value="{p["account_id"]}">'
            html += form(token, 'suspend' if p['is_active'] else 'reactivate', target)
            html += form(token, 'reset_password', target+'<label>Temporary password <input name="password" type="password" autocomplete="new-password" minlength="12" maxlength="128" required></label>')
        html += '</section>'
    html += '<h2>Settlements</h2><ul>'
    for s in settlements:
        html += f'<li>#{s["settlement_id"]} {escape(s["settlement_name"])} · account #{s["account_id"]} · season #{s["season_id"]} · {escape(s["status"])}</li>'
    html += '</ul>'+operational+'<h2>Announcement</h2>'+form(token, 'announce', '<label>Public announcement <textarea name="body" maxlength="200" required></textarea></label>')
    html += '<h2>Board moderation — latest 100 posts</h2>'
    for p in posts:
        html += f'<article><p>#{p["post_id"]} · season #{p["season_id"]} · {escape(p["username"])} · {p["moderation_status"]}</p><p>{escape(p["body"])}</p>'
        html += form(token, 'hide_post' if p['moderation_status']=='visible' else 'restore_post', f'<input type="hidden" name="target" value="{p["post_id"]}">')+'</article>'
    html += '<h2>Audit log — latest 100 actions</h2><ul>'
    for log in logs:
        html += f'<li>#{log["admin_action_id"]} · {log["occurred_at"]} UTC Unix time · {escape(log["username"])} · {escape(log["action_type"])} · {escape(log["target_type"])} #{log["target_id"]} · {escape(log["reason"])}<br>Before: {escape(log["before_values"] or "{}")}<br>After: {escape(log["after_values"] or "{}")}</li>'
    return html+'</ul>'

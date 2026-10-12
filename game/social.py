"""Shared transaction, player visibility and form helpers for social features."""
from contextlib import closing, contextmanager
from html import escape
import sqlite3

from database.create_database import connect_database
from game.settlement import CURRENT_ACCOUNT, read_state
from game.trading import player_state, eligible


@contextmanager
def transaction(path, now, *, gameplay=True, new=True):
    if CURRENT_ACCOUNT.get() is None:
        raise ValueError('Log in first.')
    with closing(connect_database(path)) as c, c:
        c.row_factory = sqlite3.Row
        c.execute('BEGIN IMMEDIATE')
        state = read_state(c)
        if not state:
            raise ValueError('Create a settlement first.')
        if gameplay:
            state = player_state(c, state['settlement']['settlement_id'], now)
            eligible(c, state, now, transactional=new)
        elif now < state['settlement']['simulation_processed_at']:
            raise ValueError('The clock is earlier than the saved state.')
        yield c, state


def other(c, state, sid, now, *, gameplay=True):
    if type(sid) is not int or sid == state['settlement']['settlement_id']:
        raise ValueError('Choose another settlement.')
    row = c.execute('''SELECT s.*,a.is_active FROM settlements s JOIN accounts a USING(account_id)
        WHERE s.settlement_id=? AND s.season_id=?''', (sid, state['season']['season_id'])).fetchone()
    if not row or not row['is_active']:
        raise ValueError('Choose a player in this season.')
    if not gameplay:
        return dict(row)
    result = player_state(c, sid, now)
    eligible(c, result, now, transactional=False)
    return result


def players(c, state):
    return c.execute('''SELECT s.settlement_id,s.settlement_name,s.account_id FROM settlements s
        JOIN accounts a USING(account_id) WHERE season_id=? AND settlement_id!=? AND a.is_active=1
        ORDER BY s.settlement_name,s.settlement_id''',
        (state['season']['season_id'], state['settlement']['settlement_id'])).fetchall()


def notify(c, account, season, kind, text, now, related=None, rid=None):
    c.execute('''INSERT INTO notifications(account_id,season_id,notification_type,message,created_at,related_type,related_id)
        VALUES (?,?,?,?,?,?,?)''', (account, season, kind, text, now, related, rid))


def news(c, season, kind, headline, now):
    c.execute('INSERT INTO news_events(season_id,event_type,occurred_at,headline) VALUES (?,?,?,?)',
              (season, kind, now, headline))


def form(token, route, action, fields='', label=None):
    return (f'<form method="post" action="/{route}"'+(f' aria-label="{escape(label,quote=True)}"' if label else '')+'>'
            f'<input type="hidden" name="token" value="{escape(token,quote=True)}">'
            f'<input type="hidden" name="action" value="{action}">{fields}')


def options(rows):
    return ''.join(f'<option value="{r["settlement_id"]}">{escape(r["settlement_name"])}</option>' for r in rows)


def hidden(name, value):
    return f'<input type="hidden" name="{name}" value="{value}">'

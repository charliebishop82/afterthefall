"""Persistent private mail, season board, public news and read notifications."""
from game.read_queries import read_connection
from contextlib import closing
from html import escape
import hashlib
import json
import sqlite3
from database.create_database import connect_database
from game import social
from game.settlement import CURRENT_ACCOUNT

SUBJECT_LIMIT = 80
BODY_LIMIT = 1000
MESSAGE_RATE = 20  # per real minute; communication does not consume game time
BOARD_RATE = 10


def text(value, maximum):
    if not isinstance(value,str):raise ValueError('Enter text.')
    value=value.strip().replace('\r\n','\n')
    if not 1<=len(value)<=maximum or any(ord(ch)<32 and ch not in '\n\t' for ch in value):
        raise ValueError(f'Enter 1–{maximum} characters without control characters.')
    return value


def transact(path, action, now, *, target_id=None, subject='', body='', message_id=None, post_id=None, reason=''):
    if action not in ('send','read','archive','post','read_notifications'):
        raise ValueError('Unknown communication action.')
    with social.transaction(path,now,gameplay=False) as (c,state):
        aid=CURRENT_ACCOUNT.get();season=state['season']['season_id']
        if action in ('send','post') and (state['season']['status']=='finished' or now>=state['season']['ends_at']):
            raise ValueError('This season is a read-only archive.')
        if action in ('send','post'):
            account=c.execute('SELECT is_active FROM accounts WHERE account_id=?',(aid,)).fetchone()
            if not account or not account[0] or state['settlement']['status']=='archived':raise ValueError('This account cannot post.')
            body=text(body,BODY_LIMIT)
        if action=='send':
            other=social.other(c,state,target_id,now,gameplay=False);subject=text(subject,SUBJECT_LIMIT)
            if c.execute('SELECT count(*) FROM private_messages WHERE sender_account_id=? AND sent_at>?',(aid,now-60)).fetchone()[0]>=MESSAGE_RATE:
                raise ValueError('Please wait before sending more messages.')
            mid=c.execute('INSERT INTO private_messages(sender_account_id,recipient_account_id,season_id,subject,body,sent_at) VALUES (?,?,?,?,?,?)',(aid,other['account_id'],season,subject,body,now)).lastrowid
            social.notify(c,other['account_id'],season,'private_message',f'New message from {state["settlement"]["settlement_name"]}.',now,'private_message',mid)
            return mid
        if action in ('read','archive'):
            row=c.execute('SELECT * FROM private_messages WHERE message_id=?',(message_id,)).fetchone()
            if not row or row['season_id']!=season or aid not in (row['sender_account_id'],row['recipient_account_id']):raise ValueError('Choose one of your messages.')
            if action=='read':
                if row['recipient_account_id']!=aid:raise ValueError('Only the recipient can mark a message read.')
                c.execute('UPDATE private_messages SET read_at=coalesce(read_at,?) WHERE message_id=?',(now,message_id))
                c.execute("UPDATE notifications SET read_at=coalesce(read_at,?) WHERE account_id=? AND related_type='private_message' AND related_id=?",(now,aid,message_id))
            else:
                column='sender_archived_at' if row['sender_account_id']==aid else 'recipient_archived_at'
                c.execute(f'UPDATE private_messages SET {column}=coalesce({column},?) WHERE message_id=?',(now,message_id))
            return message_id
        if action=='post':
            if c.execute('SELECT count(*) FROM board_posts WHERE author_account_id=? AND created_at>?',(aid,now-60)).fetchone()[0]>=BOARD_RATE:raise ValueError('Please wait before posting again.')
            return c.execute('INSERT INTO board_posts(season_id,author_account_id,body,created_at) VALUES (?,?,?,?)',(season,aid,body,now)).lastrowid
        c.execute('UPDATE notifications SET read_at=? WHERE account_id=? AND season_id=? AND read_at IS NULL',(now,aid,season))


def panel(path,state,token,now):
    aid=state['settlement']['account_id'];season=state['season']['season_id']
    with closing(connect_database(path)) as c:
        c.row_factory=sqlite3.Row;people=social.players(c,state)
        messages=c.execute('''SELECT m.*,a.display_name AS sender,b.display_name AS recipient FROM private_messages m
            JOIN accounts a ON a.account_id=m.sender_account_id JOIN accounts b ON b.account_id=m.recipient_account_id
            WHERE m.season_id=? AND (m.sender_account_id=? OR m.recipient_account_id=?) ORDER BY message_id DESC''',(season,aid,aid)).fetchall()
        posts=c.execute('''SELECT p.*,a.display_name FROM board_posts p JOIN accounts a ON a.account_id=p.author_account_id
            WHERE p.season_id=? AND p.moderation_status='visible' ORDER BY post_id DESC LIMIT 50''',(season,)).fetchall()
        news=c.execute('SELECT headline FROM news_events WHERE season_id=? ORDER BY news_id DESC LIMIT 30',(season,)).fetchall()
        notes=c.execute('SELECT message,read_at FROM notifications WHERE account_id=? AND season_id=? ORDER BY notification_id DESC LIMIT 30',(aid,season)).fetchall()
    html='<section class="production-panel" id="messages"><h2>Player messages</h2><p>Private inbox and outbox. Messages persist across restarts; this is mail rather than live chat.</p>'
    if people:
        fields=f'<label>Recipient <select name="target_id">{social.options(people)}</select></label><label>Subject <input name="subject" maxlength="80" required></label><label>Message <textarea name="body" maxlength="1000" required></textarea></label><button>Send message</button></form>'
        html+=social.form(token,'communication','send',fields,'Send message')
    for incoming,archived,title in ((True,False,'Inbox'),(False,False,'Outbox'),(True,True,'Archived inbox'),(False,True,'Archived outbox')):
        html+=f'<h3>{title}</h3>'
        for m in messages:
            if (m['recipient_account_id']==aid)!=incoming or (m['recipient_archived_at' if incoming else 'sender_archived_at'] is not None)!=archived:continue
            html+=f'<article class="building-controls"><h4>{escape(m["subject"])}</h4><p>{escape(m["sender"])} → {escape(m["recipient"])} · '+('Read' if m['read_at'] is not None else 'Unread')+'</p><p style="white-space:pre-wrap">'+escape(m['body'])+'</p>'
            if incoming and m['read_at'] is None:html+=social.form(token,'communication','read',social.hidden('message_id',m['message_id'])+f'<button>Mark message #{m["message_id"]} read</button></form>')
            if not archived:html+=social.form(token,'communication','archive',social.hidden('message_id',m['message_id'])+f'<button>Archive message #{m["message_id"]}</button></form>')
            html+='</article>'
    html+='</section><section class="production-panel" id="board"><h2>Season message board</h2>'
    html+=social.form(token,'communication','post','<label>Public post <textarea name="body" maxlength="1000" required></textarea></label><button>Post to board</button></form>','Post to board')
    for p in posts:
        html+=f'<article class="building-controls"><p>{escape(p["display_name"])} · #{p["post_id"]} · {p["moderation_status"]}</p><p style="white-space:pre-wrap">{escape(p["body"])}</p>'
        html+='</article>'
    html+='</section><section class="production-panel"><h2>Public news</h2>'+''.join('<p>'+escape(n['headline'])+'</p>' for n in news)+'</section>'
    html+='<section class="production-panel"><h2>Your notifications</h2>'+social.form(token,'communication','read_notifications','<button>Mark notifications read</button></form>')
    html+=''.join('<p>'+('Unread: ' if n['read_at'] is None else '')+escape(n['message'])+'</p>' for n in notes)
    return html+'</section>'


def revision(path,state,now,*,connection=None):
    """Wake the existing refresher without leaking private message contents."""
    aid=state['settlement']['account_id'];sid=state['settlement']['settlement_id'];season=state['season']['season_id']
    with read_connection(path,connection,rows=False) as c:
        rows=[c.execute(query,args).fetchall() for query,args in (
            ('SELECT listing_id,status,remaining_quantity FROM market_listings WHERE season_id=? ORDER BY listing_id',(season,)),
            ('SELECT treaty_id,status,cancelled_at,expires_at,coalesce(cooldown_until,0)>? FROM treaties WHERE season_id=? AND (settlement_a_id=? OR settlement_b_id=?) ORDER BY treaty_id',(now,season,sid,sid)),
            ('SELECT message_id,read_at,sender_archived_at,recipient_archived_at FROM private_messages WHERE season_id=? AND (sender_account_id=? OR recipient_account_id=?) ORDER BY message_id',(season,aid,aid)),
            ('SELECT post_id,moderation_status FROM board_posts WHERE season_id=? ORDER BY post_id',(season,)),
            ('SELECT notification_id,read_at FROM notifications WHERE account_id=? AND season_id=? ORDER BY notification_id',(aid,season)),
            ('SELECT max(news_id) FROM news_events WHERE season_id=?',(season,)))]
        from game.market import stock
        rows.append(sorted(stock(c,season).items()))
        # Wake panels at daily rollover even when no other player has traded.
        rows.append(now//86400)
        rows.append([(r["expedition_id"],r["status"]) for r in state.get("expeditions",[])])
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()[:16]

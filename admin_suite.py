"""Independent, loopback-only operator console. Uses the game's transactional services."""
import argparse
from contextlib import closing
from html import escape
import logging
import json
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
import secrets
import sqlite3
from string import Template
import time
from urllib.parse import parse_qs

from flask import Flask, Response, g, redirect, request
from database.create_database import connect_database
from game import accounts, admin, diagnostics, hosting, lobby

ROOT = Path(__file__).resolve().parent
COOKIE = 'admin_console_session'


def create_app(database=None, *, clock=time.time, port=8768, log_path=None, player_log_path=None):
    database = Path(database or ROOT/'database/playtest.db').resolve()
    if not database.is_file(): raise ValueError('Start the game once to create the playtest save.')
    with closing(connect_database(database)) as c:
        from manage import check
        check(c)
    from game import bots
    bots.prepare(database)
    app = Flask(__name__, static_folder=str(ROOT/'static'))
    app.config['MAX_CONTENT_LENGTH'] = 4096
    app.game_database = database
    allowed = hosting.authorities(port, ())
    logger = logging.Logger('admin-suite')
    if log_path:
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logger.addHandler(handler)
    else: logger.addHandler(logging.NullHandler())
    app.extensions['operator_logger'] = logger

    def stamp(): return int(clock())
    def text(message, status=400): return Response(message, status=status, content_type='text/plain; charset=utf-8')
    def rotate(aid):
        g.cookie, g.actor = accounts.new_session(database, aid, stamp(), request.cookies.get(COOKIE))
    def page(body):
        nav = '<div class="operator-heading"><div><p class="eyebrow">LOCAL ADMINISTRATION</p><h1>Operator console</h1></div><span>Save: '+escape(database.name)+'</span></div><nav class="operator-nav"><a href="/">Dashboard</a><a href="/players">Players & maps</a><a href="/logs">Logs</a><a href="/performance">Performance</a><a href="/diagnostics">Diagnostics</a><a href="/controls?section=season">Season</a><a href="/controls?section=accounts">Accounts</a><a href="/controls?section=corrections">Corrections</a><a href="/controls?section=moderation">Moderation</a><a href="/controls?section=audit">Audit</a><a href="/bots">Bots</a></nav>'
        if g.actor and g.actor['account_id'] is not None:
            nav += f'<form method="post" action="/logout"><input type="hidden" name="token" value="{escape(g.actor["csrf"],quote=True)}"><button>Log out of console</button></form>'
        html=Template((ROOT/'templates/base.html').read_text(encoding='utf-8')).substitute(title='Operator suite',status='ADMIN',content=nav+body)
        return html.replace('</head>','<link rel="stylesheet" href="/static/admin.css"></head>').replace('<body>','<body class="operator-app">')

    @app.before_request
    def authenticate():
        g.actor=None; g.cookie=None
        if request.host.lower() not in allowed: return text('Use the local operator address.',403)
        g.actor=accounts.session(database,request.cookies.get(COOKIE),stamp())
        if request.path.startswith('/static/'): return None
        if request.method=='POST':
            if request.path not in ('/login','/logout','/admin','/lobby','/bots'): return text('Not found.',404)
            if request.headers.get('Origin') not in (None,request.host_url.rstrip('/')): return text('Request origin rejected.',403)
            if not g.actor: return text('Reload the login page.',403)
            if request.mimetype!='application/x-www-form-urlencoded': return text('Expected a form.',415)
            if not 0<(request.content_length or 0)<=4096: return text('Invalid form size.',413)
            try:
                form=parse_qs(request.get_data().decode('utf-8'),keep_blank_values=True,max_num_fields=8)
                if any(len(v)!=1 for v in form.values()): raise ValueError()
            except (ValueError,UnicodeError): return text('Invalid form.',400)
            if not secrets.compare_digest(form.get('token',[''])[0].encode(),g.actor['csrf'].encode()): return text('Reload the page first.',403)
            g.form={k:v[0] for k,v in form.items()}
        if request.path not in ('/login','/logout'):
            if not g.actor or g.actor['account_id'] is None: return redirect('/login',303)
            with closing(connect_database(database)) as c: admin.require(c,g.actor['account_id'])

    @app.after_request
    def headers(response):
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Security-Policy':"default-src 'self'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"})
        if g.get('cookie'): response.set_cookie(COOKIE,g.cookie,max_age=86400,httponly=True,samesite='Strict')
        # Fixed route names only: never record credentials, tokens or query strings.
        route=request.url_rule.rule if request.url_rule else '(unknown route)'
        logger.info('%s %s status=%s',request.method,route,response.status_code)
        return response

    @app.errorhandler(ValueError)
    def invalid(error): return text(str(error),400)
    @app.errorhandler(PermissionError)
    def forbidden(error): return text(str(error),403)
    @app.errorhandler(sqlite3.Error)
    def storage(error):
        logger.error('Database operation failed: %s',type(error).__name__)
        return text('Database operation failed. Check diagnostics; no save was reset.',500)

    @app.route('/login',methods=['GET','POST'])
    def login():
        if request.method=='POST':
            aid=accounts.authenticate(database,g.form.get('username',''),g.form.get('password',''),stamp())
            if aid is None: return text('Login failed. Check your details or try again shortly.',400)
            with closing(connect_database(database)) as c: admin.require(c,aid)
            rotate(aid); return redirect('/',303)
        if not g.actor: rotate(None)
        return page(f'<p>Administrator accounts only. No settlement enrollment required.</p><form method="post" action="/login"><input type="hidden" name="token" value="{escape(g.actor["csrf"],quote=True)}"><label>Username <input name="username" autocomplete="username" maxlength="24" required></label><label>Password <input type="password" name="password" autocomplete="current-password" maxlength="128" required></label><button>Log in to console</button></form>')

    @app.post('/logout')
    def logout(): rotate(None); return redirect('/login',303)

    @app.get('/')
    def dashboard():
        from game.operator_views import dashboard as dashboard_view
        return page(dashboard_view(database,stamp()))

    @app.get('/controls')
    @app.get('/admin')
    def controls():
        state=lobby.status(database)
        body=f'<p>Save: {escape(str(database))}</p><h2>Shared-start lobby</h2><p>{escape(state["status"])}</p><ul>'+''.join('<li>'+escape(m['settlement_name'])+'</li>' for m in state['members'] if m['is_active'])+'</ul>'
        if state['status']=='waiting':
            body+=f'<form method="post" action="/lobby"><input type="hidden" name="token" value="{escape(g.actor["csrf"],quote=True)}"><label>Launch reason <input name="reason" maxlength="200" required></label><button>Start playtest for all ready players</button></form>'
        if request.args.get('section','season')!='season': body=''
        from game.operator_views import control_sections
        return page(body+control_sections(admin.panel(database,g.actor['account_id'],g.actor['csrf']),request.args.get('section','season')))

    @app.get('/players')
    def players():
        from game.operator_views import players as player_view
        return page(player_view(database))

    @app.get('/players/<int:settlement_id>')
    def inspect_player(settlement_id):
        from game.operator_views import inspect_player as inspect_view
        return page(inspect_view(database,settlement_id))

    @app.get('/bots')
    def bots_page():
        return page(bots.panel(database,g.actor['csrf']))

    @app.post('/bots')
    def bot_control():
        f=g.form
        if f.get('action')=='create':
            bots.create(database,g.actor['account_id'],f.get('username',''),f.get('name',''),stamp(),personality=f.get('personality','balanced'))
        else:
            bots.control(database,g.actor['account_id'],int(f.get('target','0')),f.get('action',''),stamp())
        return redirect('/bots',303)

    @app.get('/bot-traces')
    def bot_traces():
        aid=int(request.args.get('account','0'))
        before=int(request.args.get('before','9223372036854775807'))
        with closing(connect_database(database)) as c:
            c.row_factory=sqlite3.Row
            rows=[dict(r) for r in c.execute('SELECT * FROM bot_traces WHERE account_id=? AND trace_id<? ORDER BY trace_id DESC LIMIT 200',(aid,before))]
        for row in rows: row['payload']=json.loads(row['payload'])
        if request.args.get('format')=='json':
            response=Response(json.dumps(rows,indent=2),content_type='application/json')
            response.headers['Content-Disposition']='attachment; filename="bot-traces.json"'
            return response
        body=f'<h2>Bot #{aid} decision traces</h2><p>Retained history; newest 200 records per page. Snapshots contain only this bot’s observed state. Transport errors can have an unknown action outcome.</p><a href="/bot-traces?account={aid}&amp;before={before}&amp;format=json">Export this page as JSON</a>'
        for row in rows:
            body+=f'<details><summary>#{row["trace_id"]} · {escape(row["timestamp_utc"])} · {escape(row["phase"])}</summary><pre>{escape(json.dumps(row["payload"],indent=2))}</pre></details>'
        if rows:body+=f'<a href="/bot-traces?account={aid}&amp;before={rows[-1]["trace_id"]}">Older traces</a>'
        return page(body)

    @app.post('/lobby')
    def launch(): lobby.start(database,g.actor['account_id'],stamp(),g.form.get('reason','')); return redirect('/',303)

    @app.post('/admin')
    def correct():
        f=g.form
        def number(key,convert): return convert(f[key]) if f.get(key) else None
        admin.transact(database,g.actor['account_id'],f.get('action',''),stamp(),target=number('target',int),reason=f.get('reason',''),password=f.get('password',''),body=f.get('body',''),settlement_id=number('settlement_id',int),field=f.get('field',''),value=number('value',float),expected=number('expected',float))
        return redirect('/',303)

    @app.get('/diagnostics')
    def checks():
        report=diagnostics.inspect(database)
        body='<h2>Read-only diagnostics</h2><p>Checks examine a committed snapshot; they do not advance game time or repair data automatically.</p>'
        body+='<p>'+('All implemented checks passed.' if report['ok'] else 'Issues require review.')+'</p><ul>'
        body+=''.join(f'<li>{escape(level)}: {escape(name)} — {escape(detail)}</li>' for level,name,detail in report['findings'])+'</ul>'
        body+='<pre>'+escape(str(report['counts']))+'</pre>'
        return page(body)

    @app.get('/logs')
    def logs():
        def numeric(key):
            value=request.args.get(key)
            return int(value) if value else None
        kind=request.args.get('kind') or None
        rows=diagnostics.events(database,settlement=numeric('settlement'),kind=kind,before=numeric('before'))
        if request.args.get('format')=='json':
            import json
            response=Response(json.dumps([dict(event_id=r[0],occurred_at=r[1],settlement_id=r[2],event_type=r[3],event_data=json.loads(r[4])) for r in rows],indent=2),content_type='application/json')
            response.headers['Content-Disposition']='attachment; filename="game-events.json"'
            return response
        from game.bot_runtime import fallback_panel
        body='<div class="operator-links"><a href="/player-logs">Player requests & errors</a><a href="/controls?section=audit">Correction audit</a></div><h2>Game events — up to 100</h2><form method="get" action="/logs"><label>Settlement ID <input name="settlement" type="number" min="1"></label><label>Event type <input name="kind" maxlength="80"></label><label>Before event ID <input name="before" type="number" min="1"></label><label>Download JSON <input type="checkbox" name="format" value="json"></label><button>Search / export</button></form>'
        body+='<pre>'+escape('\n'.join(str(row) for row in rows))+'</pre>'
        body+=fallback_panel(database)
        if rows:
            from urllib.parse import urlencode
            query={key:value for key,value in request.args.items() if key in ('settlement','kind')}
            query['before']=rows[-1][0]
            body+='<a href="/logs?'+escape(urlencode(query),quote=True)+'">Older matching events</a>' 
        if log_path:
            with Path(log_path).open('rb') as stream:
                stream.seek(0,2); size=stream.tell(); stream.seek(max(0,size-32768))
                tail=stream.read().decode('utf-8',errors='replace')
            body+='<h2>Operator service — last 32 KB</h2><pre>'+escape(tail)+'</pre>'
        body+='<p>Permanent before/after audit history is shown under Controls. File logs rotate at 1 MB; three older files are retained.</p>'
        return page(body)

    @app.get('/performance')
    def performance():
        from game.performance import panel
        from game.background import panel as background_panel
        return page(panel(player_log_path,database)+background_panel(database))

    @app.get('/player-logs')
    def player_logs():
        # Fixed rotation suffixes only: query parameters never select arbitrary paths.
        rotation = int(request.args.get('rotation', '0'))
        if rotation not in range(6): raise ValueError('Choose log file 0 through 5.')
        account = request.args.get('account', '').strip()
        if account:
            account = int(account)
            if account < 1: raise ValueError('Account ID must be positive.')
        correlation = request.args.get('request_id', '').strip()
        if correlation and (len(correlation) != 32 or any(c not in '0123456789abcdef' for c in correlation)):
            raise ValueError('Request ID must contain 32 lowercase hexadecimal characters.')
        errors_only = request.args.get('errors') == '1'
        records = []; skipped = 0; notice = ''
        if player_log_path is None:
            notice = 'Player log is not configured for this console.'
        else:
            source = Path(player_log_path)
            if rotation: source = source.with_name(source.name + '.' + str(rotation))
            try:
                with source.open('rb') as stream:
                    stream.seek(0, 2); offset = max(0, stream.tell() - 262144)
                    stream.seek(offset)
                    if offset: stream.readline(262144)  # Discard an incomplete leading record.
                    lines = stream.read(262144).decode('utf-8', errors='replace').splitlines()
                for line in reversed(lines):
                    try: record = json.loads(line)
                    except (ValueError, RecursionError):
                        skipped += 1; continue
                    if not isinstance(record, dict):
                        skipped += 1; continue
                    if record.get('database') != database.name: continue
                    if account and record.get('account_id') != account: continue
                    if correlation and record.get('request_id') != correlation: continue
                    status = record.get('status')
                    if errors_only and (not isinstance(status, int) or status < 400): continue
                    records.append(record)
                    if len(records) == 100: break
            except FileNotFoundError:
                notice = 'No records in this file yet. Restart the player server to enable logging, or select another file.'
            except OSError:
                notice = 'Unable to read the player log. Check file permissions in the console terminal.'
        if request.args.get('format') == 'json':
            response = Response(json.dumps(records, indent=2), content_type='application/json')
            response.headers['Content-Disposition'] = 'attachment; filename="player-requests.json"'
            return response
        options = ''.join(f'<option value="{i}"'+(' selected' if i == rotation else '')+'>'+('Current' if i == 0 else f'Older file {i}')+'</option>' for i in range(6))
        body = '<h2>Player requests and errors</h2><p>Read-only view for save '+escape(database.name)+'. Newest first: up to 100 matching records from the last 256 KB of the selected file. Reload to see new requests. UTC timestamps and request IDs connect attempts to results.</p>'
        body += '<form method="get" action="/player-logs"><label>Log file <select name="rotation">'+options+'</select></label><label>Account ID <input name="account" type="number" min="1" value="'+escape(str(account or ''), quote=True)+'"></label><label>Request ID <input name="request_id" maxlength="32" value="'+escape(correlation, quote=True)+'"></label><label>Errors only <input type="checkbox" name="errors" value="1"'+(' checked' if errors_only else '')+'></label><label>Download JSON <input type="checkbox" name="format" value="json"></label><button>Search / export</button></form>'
        if notice: body += '<p>'+escape(notice)+'</p>'
        if skipped: body += f'<p>Skipped {skipped} incomplete or invalid records.</p>'
        from game.operator_views import request_table
        body += request_table(records)+'<p>Full successful gameplay events remain on <a href="/logs">Logs</a>. Player files retain the current log and five rotated files; this is recent troubleshooting history.</p>'
        return page(body)

    return app


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,default=ROOT/'database/playtest.db')
    parser.add_argument('--port',type=int,default=8768)
    parser.add_argument('--player-log-file',type=Path,default=ROOT/'logs/player-actions.jsonl',help='Player JSONL log to read, matching serve_game.py --log-file')
    args=parser.parse_args(argv)
    if not 1<=args.port<=65535: parser.error('Invalid port.')
    from waitress import serve
    app=create_app(args.database,port=args.port,log_path=ROOT/'logs/admin-suite.log',player_log_path=args.player_log_file)
    print(f'Operator suite: http://127.0.0.1:{args.port} — {app.game_database}',flush=True)
    serve(app,host='127.0.0.1',port=args.port,threads=2,max_request_body_size=4096,expose_tracebacks=False)


if __name__=='__main__': main()

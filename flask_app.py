"""Flask transport for the existing game services and a fresh shared-start playtest."""
from contextlib import closing
from html import escape
from functools import wraps
from threading import RLock
from pathlib import Path
import secrets
import sqlite3
from string import Template
import time
from urllib.parse import parse_qs, urlsplit

from flask import Flask, Response, g, jsonify, redirect, request, send_file
from database.create_database import connect_database
from game import accounts, admin, lobby, hosting, web_views
from game.settlement import account_scope

ROOT=Path(__file__).resolve().parent
COOKIE='playtest_session'
GAME_ROUTES={'/administrator','/buildings','/scavenging','/needs','/manufacturing','/trade','/conflict','/market','/diplomacy','/communication','/bank','/advisor','/expeditions'}
POST_ROUTES=GAME_ROUTES|{'/login','/register','/logout','/settlement','/lobby','/admin','/account','/clock'}


def public_origin(value):
    if not value:return None
    parts=urlsplit(value)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.path not in ('','/') or parts.query or parts.fragment:
        raise ValueError('Public URL must be an HTTPS origin without a path, credentials or query.')
    host=hosting.hostname(parts.hostname)
    port=parts.port
    return f'https://{host}'+(f':{port}' if port and port!=443 else '')


def create_app(database=None, *, clock=time.time, port=8767, allowed_hosts=(), public_url=None, log_path=None):
    database=Path(database or ROOT/'database/playtest.db').resolve()
    external=public_origin(public_url)
    allowed=hosting.authorities(port,allowed_hosts)
    if external:allowed.add(urlsplit(external).netloc)
    lobby.prepare(database)
    app=Flask(__name__,static_folder=str(ROOT/'static'))
    app.config.update(MAX_CONTENT_LENGTH=16384,TESTING=False)
    app.game_database=database
    app.config['PLAYER_LOG_ROUTES']=POST_ROUTES
    from game.request_logging import install_request_logging, mark_error
    install_request_logging(app,database,log_path,clock)

    # One player-server simulation/action at a time, before sampling its clock.
    # This also covers different players: refresh can process shared-season work.
    # SQLite still protects transactions; this gate prevents stale request times.
    gameplay_lock = RLock()

    def serialized_gameplay(view):
        @wraps(view)
        def ordered(*args, **kwargs):
            with gameplay_lock:
                return view(*args, **kwargs)
        return ordered

    def now():return int(clock())
    def text(message,status=400):return Response(message,status=status,content_type='text/plain; charset=utf-8')
    def page(title,body):
        if g.actor and g.actor['account_id'] is not None:body=web_views.navigation(g.actor,g.actor['csrf'])+body
        return Template((ROOT/'templates/base.html').read_text(encoding='utf-8')).substitute(title=title,status='PLAYTEST',content=body)
    def rotate(aid):
        token,_=accounts.new_session(database,aid,now(),request.cookies.get(COOKIE))
        g.actor=accounts.session(database,token,now());g.cookie=token
        enrich_actor()
    def enrich_actor():
        if g.actor and g.actor['account_id'] is not None:
            with closing(connect_database(database)) as c:
                g.actor['is_admin']=bool(c.execute('SELECT is_admin FROM accounts WHERE account_id=?',(g.actor['account_id'],)).fetchone()[0])
    def logged_in():return g.actor and g.actor['account_id'] is not None
    def auth_page():
        if not g.actor:rotate(None)
        token=escape(g.actor['csrf'],quote=True)
        body='<h1>Your playtest account</h1><p>Register and choose a settlement name. Before launch everyone starts together; during an active season new players start when they join.</p>'
        body+='<p>New player? <a href="/help">Read the beginner player guide</a>.</p>'
        if lobby.status(database)['status']=='started':body+='<p>The playtest has started. You can join while enrollment remains open.</p>'
        for action,label in (('login','Log in'),('register','Create account')):
            body+=f'<section class="production-panel"><h2>{label}</h2><form aria-label="{label} form" method="post" action="/{action}"><input type="hidden" name="token" value="{token}"><label>Username <input name="username" autocomplete="username" required minlength="3" maxlength="24"></label><label>Password <input name="password" type="password" autocomplete="{"current-password" if action=="login" else "new-password"}" required minlength="12" maxlength="128"></label><button>{label}</button></form></section>'
        return page('Playtest accounts',body)
    def lobby_page():
        state=lobby.status(database)
        body='<h1>Playtest lobby</h1>'
        with closing(connect_database(database)) as c:
            c.row_factory=sqlite3.Row
            season=c.execute('SELECT * FROM seasons ORDER BY season_id DESC LIMIT 1').fetchone()
        can_join=state['status']=='waiting' or lobby.enrollment_open(season,now())
        if can_join:
            if state['status']=='started':
                body+='<p>Join with normal starting supplies and protection, with no catch-up grant. '+('Reserve now; your settlement starts when the administrator resumes the season.' if season['status']=='paused' else 'Your settlement starts now and shares the existing season end date.')+'</p>'
            else:
                body+='<p>No game time runs before the host starts. Reserve a settlement name to join the shared start.</p>'
            own=next((m for m in state['members'] if m['account_id']==g.actor['account_id']),None)
            body+=f'<form aria-label="Reserve settlement" method="post" action="/settlement"><input type="hidden" name="token" value="{escape(g.actor["csrf"],quote=True)}"><label>Settlement name <input name="name" value="{escape(own["settlement_name"] if own else "",quote=True)}" maxlength="40" required></label><button>Reserve settlement</button></form>'
            body+='<h2>Ready players</h2><ul>'+''.join('<li>'+escape(m['settlement_name'])+'</li>' for m in state['members'] if m['is_active'])+'</ul>'
            body+='<p><a href="/">Refresh lobby</a>. This page checks for launch automatically.</p><div id="playtest-lobby" data-status="waiting"></div><script src="/static/lobby.js" defer></script>'
        else:body+='<p>Settlement enrollment is closed during finalization and after the season ends.</p>'
        if state['status']=='started': body=body.replace('data-status="waiting"','data-status="started"')
        if state['status']=='started' and can_join and season['status']=='active': body=body.replace('Reserve settlement</button>','Join season</button>')
        return page('Playtest lobby',body)

    @app.before_request
    def authenticate_request():
        g.actor=None;g.cookie=None
        authority=request.host.lower()
        if authority not in allowed:return text('Use a configured server address.',403)
        if external and authority==urlsplit(external).netloc and request.scheme!='https':
            return text('This public address requires HTTPS through the configured local proxy.',403)
        g.actor=accounts.session(database,request.cookies.get(COOKIE),now())
        enrich_actor()
        g.player_account_id=g.actor['account_id'] if g.actor else None
        if request.method=='POST':
            if request.path not in POST_ROUTES:return text('Not found.',404)
            if request.headers.get('Origin') not in (None,request.host_url.rstrip('/')):
                return text('Request origin rejected.',403)
            if not g.actor:return text('Reload and log in before submitting.',403)
            if request.mimetype!='application/x-www-form-urlencoded':return text('Expected a form.',415)
            limit=16384 if request.path=='/communication' else 4096
            if not 0<(request.content_length or 0)<=limit:return text('Invalid form size.',413)
            try:
                form=parse_qs(request.get_data().decode('utf-8'),keep_blank_values=True,max_num_fields=64 if request.path in ('/conflict','/expeditions') else 8)
                if any(len(v)!=1 for k,v in form.items() if not ((request.path=='/conflict' and k in ('citizen_id','drone_id') or request.path=='/expeditions' and k=='citizen_id'))):
                    raise ValueError('Duplicate form fields.')
            except (ValueError,UnicodeError):return text('Invalid form.',400)
            if not secrets.compare_digest(form.get('token',[''])[0].encode(),g.actor['csrf'].encode()):
                return text('Reload the page first.',403)
            g.form=form

    @app.after_request
    def response_headers(response):
        response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Content-Security-Policy']="default-src 'self'; style-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        if request.path=='/help':
            # The offline handbook contains its own styles and vector diagrams.
            # It contains no scripts; keep its narrow policy separate from gameplay.
            response.headers['Content-Security-Policy']="default-src 'none'; style-src 'unsafe-inline'; img-src data:; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        response.headers['Referrer-Policy']='same-origin'
        if g.get('cookie'):
            response.set_cookie(COOKIE,g.cookie,max_age=86400,httponly=True,samesite='Strict',secure=bool(external and request.host.lower()==urlsplit(external).netloc))
        return response

    @app.errorhandler(ValueError)
    def bad_action(error):
        mark_error(error)
        return text(str(error),400)
    @app.errorhandler(PermissionError)
    def forbidden(error):
        mark_error(error)
        return text(str(error),403)
    @app.errorhandler(sqlite3.Error)
    def storage_error(error):
        mark_error(error)
        return text('Could not save. No game data was reset.',500)

    @app.errorhandler(500)
    def unexpected_error(error):
        mark_error(error.original_exception or error)
        return text('Unexpected server error. Check the player log using the request ID; no save was reset.',500)

    @app.get('/help')
    def player_help():
        # Fixed published files only. Reading help does not advance a settlement.
        content=(ROOT/'docs/player-guide.html').read_text(encoding='utf-8')
        content=content.replace('href="player-guide.pdf"','href="/help.pdf"')
        return Response(content,content_type='text/html; charset=utf-8')

    @app.get('/help.pdf')
    def player_help_pdf():
        return send_file(ROOT/'docs/player-guide.pdf',mimetype='application/pdf',as_attachment=True,download_name='Settlement-Game-Beginner-Guide.pdf')

    @app.get('/')
    @app.get('/login')
    @app.get('/register')
    @serialized_gameplay
    def index():
        if not logged_in():return auth_page()
        if lobby.status(database)['status']=='waiting':return lobby_page()
        from game import expansion
        from game.simulation import advance_settlement
        with account_scope(g.actor['account_id']):
            expansion.refresh(database,now())
            state=advance_settlement(database,now())
            if not state:return lobby_page()
            return web_views.settlement(database,state,g.actor,g.actor['csrf'],now())

    @app.get('/api/lobby')
    def lobby_status():
        if not logged_in():return text('Log in first.',401)
        state=lobby.status(database)
        with closing(connect_database(database)) as c:
            joined=bool(c.execute('SELECT 1 FROM settlements WHERE account_id=? AND season_id=(SELECT max(season_id) FROM seasons)',(g.actor['account_id'],)).fetchone())
        return jsonify(status=state['status'],started_at=state['started_at'],joined=joined)

    @app.get('/api/resources')
    @serialized_gameplay
    def resource_status():
        if not logged_in():return text('Log in first.',401)
        if lobby.status(database)['status']=='waiting':return jsonify(status='waiting')
        from game import expansion
        from game.simulation import advance_settlement
        with account_scope(g.actor['account_id']):
            expansion.refresh(database,now());state=advance_settlement(database,now())
            if not state:return text('You did not enroll before launch.',403)
            return jsonify(web_views.resources(database,state,now()))

    @app.get('/favicon.ico')
    def favicon():return Response(status=204)

    @app.get('/admin')
    def admin_page():
        if not logged_in():return text('Log in first.',401)
        with closing(connect_database(database)) as c: admin.require(c,g.actor['account_id'])
        return page('Administration', '<p>Administration runs in the separate local operator suite on port 8768. Launch start_admin.ps1 from the project folder.</p>')

    @app.get('/account')
    def account_page():
        if not logged_in():return text('Log in first.',401)
        return page('Account settings',f'<h1>Account settings</h1><p>Changing your password logs out every device.</p><form method="post" action="/account"><input type="hidden" name="token" value="{escape(g.actor["csrf"],quote=True)}"><label>Current password <input type="password" name="current" autocomplete="current-password" maxlength="128" required></label><label>New password <input type="password" name="password" autocomplete="new-password" minlength="12" maxlength="128" required></label><button>Change password</button></form>')

    @app.route('/<path:route>',methods=['POST'])
    @serialized_gameplay
    def action(route):
        path=request.path;form=g.form
        def value(name,default=''):return form.get(name,[default])[0]
        def integer(name):return int(value(name)) if value(name) else None
        aid=g.actor['account_id'];stamp=now()
        g.player_action_timestamp=stamp
        if path in ('/login','/register'):
            if logged_in():raise ValueError('Log out before changing accounts.')
            username,password=value('username'),value('password')
            if len(username)>24 or len(password)>128:raise ValueError('Invalid username or password.')
            if path=='/register':aid=accounts.register(database,username,password,stamp)
            else:
                aid=accounts.authenticate(database,username,password,stamp)
                if aid is None:raise ValueError('Login failed. Check your details or try again shortly.')
            rotate(aid);return redirect('/',303)
        if not logged_in():return text('Log in first.',401)
        if path=='/logout':rotate(None);return redirect('/',303)
        if path=='/account':
            admin.change_password(database,aid,value('current'),value('password'),stamp)
            rotate(None);return redirect('/',303)
        if path in ('/admin','/lobby'): return text('Use the separate local operator suite.',403)
        if path=='/settlement':
            lobby.enroll(database,aid,value('name'),stamp);return redirect('/',303)
        if path=='/clock':return text('Players cannot change shared time.',403)
        if lobby.status(database)['status']!='started':return text('Wait for the administrator to start the playtest.',403)
        with account_scope(aid):game_action(database,path,form,stamp)
        return redirect('/',303)

    return app


def game_action(database,path,form,now):
    """Form parsing ends here; game services retain ownership checks and transactions."""
    from game import needs, manufacturing, buildings, scavenging, simulation, trading, combat, market, diplomacy, communication, expansion
    def value(name,default=''):return form.get(name,[default])[0]
    def integer(name):return int(value(name)) if value(name) else None
    action=value('action')
    if path=='/advisor':
        if action!='report':raise ValueError('Unknown advisor action.')
        from game.advisor import request_report
        request_report(database,now)
    elif path=='/expeditions':
        from game.expeditions import command
        command(database,action,now,citizen_ids=[int(v) for v in form.get('citizen_id',[])],food=integer('food'),water=integer('water'),expedition_id=integer('expedition_id'))
    elif path=='/needs':needs.command(database,action,now,food=value('food','full'),water=value('water','full'))
    elif path=='/manufacturing':
        args={key:int(value(key)) for key in ('building_id','quantity','job_id') if key in form}
        manufacturing.command(database,action,now,unit_type=value('unit_type'),repeat=value('repeat','0')=='1',**args)
    elif path=='/scavenging':scavenging.assign(database,action,integer('derelict_id'),integer('citizen_id'),now=now,exposed=value('exposed')=='1')
    elif path=='/buildings':
        args={key:int(value(key)) for key in ('building_id','citizen_id','x','y','rotation','expected_level','unit_id') if key in form}
        if 'building_type' in form:args['building_type']=value('building_type')
        buildings.change_building(database,action,now=now,auto_builder=action=='build',exposed=value('exposed')=='1',**args)
    elif path=='/administrator':simulation.apply_action(database,'assign',citizen_id=integer('citizen_id'),now=now)
    elif path=='/trade':
        if action=='propose':trading.transact(database,action,now,recipient_id=integer('recipient_id'),offered={value('offered_resource'):float(value('offered_quantity'))},requested={value('requested_resource'):float(value('requested_quantity'))})
        else:trading.transact(database,action,now,trade_id=integer('trade_id'))
    elif path=='/conflict':combat.command(database,action,now,target_id=integer('target_id'),citizen_ids=[int(v) for v in form.get('citizen_id',[])],objective=value('objective','balanced'),drone_ids=[int(v) for v in form.get('drone_id',[])],missile_count=int(value('missile_count','0')))
    elif path=='/bank':expansion.transact(database,action,now,amount=integer('amount'),days=integer('days'),loan_id=integer('loan_id'),investment_id=integer('investment_id'))
    elif path=='/market':market.transact(database,action,now,resource=value('resource'),quantity=integer('quantity'),unit_price=integer('unit_price'),listing_id=integer('listing_id'))
    elif path=='/diplomacy':diplomacy.transact(database,action,now,target_id=integer('target_id'),treaty_type=value('treaty_type'),treaty_id=integer('treaty_id'))
    elif path=='/communication':communication.transact(database,action,now,target_id=integer('target_id'),subject=value('subject'),body=value('body'),message_id=integer('message_id'),post_id=integer('post_id'),reason=value('reason'))
    else:raise ValueError('Unknown game action.')

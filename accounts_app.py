"""Run account-based local multiplayer: python accounts_app.py (port 8767)."""
import argparse,time,secrets,sqlite3,re,json
from pathlib import Path
from http.server import ThreadingHTTPServer
from http.cookies import SimpleCookie,CookieError
from urllib.parse import parse_qs,urlsplit
from html import escape
from string import Template
from app import PrototypeHandler
from game import accounts, trading, combat, market, diplomacy, communication, expansion, expansion_views, admin, hosting
from game.settlement import account_scope,read_settlement

ROOT=Path(__file__).resolve().parent

class AccountServer(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,database,clock=time.time,allowed_hosts=()):
        self.database=Path(database).resolve();self.clock=clock
        ThreadingHTTPServer.__init__(self,address,AccountHandler)
        self.allowed_authorities=hosting.authorities(self.server_address[1],allowed_hosts)

class AccountHandler(PrototypeHandler):
    def local_request(self):
        if self.headers.get('Host', '').lower() not in self.server.allowed_authorities:
            self.reply(403,b'Use a configured server address.','text/plain; charset=utf-8')
            return False
        return True
    def valid_origin(self):
        origin=self.headers.get('Origin')
        return origin is None or origin == 'http://'+self.headers.get('Host','').lower()
    def simple_page(self,title,content):
        return Template((ROOT/'templates/base.html').read_text(encoding='utf-8')).substitute(title=title,status='ACCOUNT PROTOTYPE',content=content).encode()
    def settings_page(self):
        return self.simple_page('Account settings',f'<h1>Account settings</h1><p>Changing your password logs out all devices. Log in again with the new password.</p><form method="post" action="/account"><input type="hidden" name="token" value="{escape(self.form_token,quote=True)}"><label>Current password <input type="password" name="current" autocomplete="current-password" required maxlength="128"></label><label>New password <input type="password" name="password" autocomplete="new-password" required minlength="12" maxlength="128"></label><button>Change password</button></form>')
    @property
    def form_token(self):return self.actor['csrf']
    def end_headers(self):
        if getattr(self,'pending_cookie',None):self.send_header('Set-Cookie',self.pending_cookie)
        super().end_headers()
    def load_actor(self):
        self.pending_cookie=None;cookie=SimpleCookie()
        try:cookie.load(self.headers.get('Cookie',''))
        except CookieError:pass
        self.session_token=cookie['settlement_session'].value if 'settlement_session' in cookie else None
        self.actor=accounts.session(self.server.database,self.session_token,int(self.server.clock()))
    def rotate(self,account_id):
        self.session_token,self.actor=accounts.new_session(self.server.database,account_id,int(self.server.clock()),self.session_token)
        self.actor=accounts.session(self.server.database,self.session_token,int(self.server.clock()))
        self.pending_cookie=f'settlement_session={self.session_token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400'
    def auth_page(self,error=''):
        token=escape(self.form_token,quote=True)
        forms=''
        for action,label in [('login','Log in'),('register','Create account')]:
            forms+=f'<section class="production-panel"><div class="building-controls"><h2>{label}</h2><form aria-label="{label} form" method="post" action="/{action}"><input type="hidden" name="token" value="{token}"><label for="{action}-username">Username</label><input id="{action}-username" name="username" autocomplete="username" required maxlength="24"><label for="{action}-password">Password</label><input id="{action}-password" type="password" name="password" autocomplete="{"current-password" if action=="login" else "new-password"}" required minlength="12" maxlength="128"><button>{label}</button></form></div></section>'
        content='<h1>Your settlement account</h1><p>Create an account or log in to manage your own settlement.</p><p>Usernames use 3–24 letters, numbers or underscores. Passwords use 12–128 characters.</p>'
        if error:content+='<p class="error" role="alert">'+escape(error)+'</p>'
        return Template((ROOT/'templates/base.html').read_text(encoding='utf-8')).substitute(title='Accounts',status='ACCOUNT PROTOTYPE',content=content+forms).encode()
    def reply(self,status,body=b'',content_type='text/html; charset=utf-8',location=None):
        frozen=False
        state=None
        if self.actor and self.actor['account_id'] is not None and (content_type.startswith('text/html') or content_type=='application/json'):
            with account_scope(self.actor['account_id']):state=read_settlement(self.server.database)
            frozen=bool(state and state['settlement']['status']=='suspended')
        trade_revision=(trading.revision(self.server.database,state)+combat.revision(self.server.database,state,int(self.server.clock()))+communication.revision(self.server.database,state,int(self.server.clock()))) if state else ''
        scores=[]
        if state and state.get('expansion'):
            from contextlib import closing
            from database.create_database import connect_database
            import hashlib,sqlite3
            with closing(connect_database(self.server.database)) as c:
                c.row_factory=sqlite3.Row
                scores=expansion_views.scores(c,state)
                sid=state['settlement']['settlement_id']
                from game import banking
                signature=[[(r['settlement_id'],r['rank']) for r in scores],[(r['loan_id'],r['outstanding_balance'],r['status']) for r in banking.loans(c,sid)],[(r['investment_id'],r['principal'],r['accrued_interest']) for r in banking.investments(c,sid)]]
                trade_revision+=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()[:16]
        if state and content_type=='application/json':
            payload=json.loads(body)
            if frozen:payload['status']='suspended'
            payload['revision']=payload.get('revision','')+trade_revision
            if state.get('expansion'):
                payload['scores']=scores
                payload['own_score']=next(r['overall'] for r in scores if r['settlement_id']==state['settlement']['settlement_id'])
            payload['trade_available']={r:trading.available(state,r) for r in trading.RESOURCES}
            payload['trade_reserved']=state['reserved']
            payload['raid_timers']=combat.timers(self.server.database,state,int(self.server.clock()))
            payload['war_timers']=combat.war_timers(self.server.database,state,int(self.server.clock()))
            body=json.dumps(payload).encode()
        if content_type.startswith('text/html') and self.actor and self.actor['account_id'] is not None:
            html=body.decode('utf-8');html=re.sub(r'<form method="post" action="/clock">.*?</form>','',html,flags=re.S)
            bar=f'<div class="building-controls"><span>Logged in as {escape(self.actor["username"] or "player")}</span><form method="post" action="/logout"><input type="hidden" name="token" value="{escape(self.form_token,quote=True)}"><button class="secondary">Log out</button></form></div>'
            bar+='<nav><a href="/">Settlement</a> · <a href="/account">Account settings</a>'
            from contextlib import closing
            from database.create_database import connect_database
            with closing(connect_database(self.server.database)) as c:
                role=c.execute('SELECT is_admin FROM accounts WHERE account_id=?',(self.actor['account_id'],)).fetchone()
            if role and role[0]:bar+=' · <a href="/admin">Administration</a>'
            bar+='</nav>'
            if state and state.get('expansion'):
                own=next(r for r in scores if r['settlement_id']==state['settlement']['settlement_id'])
                bar+=f'<p>Overall score: <span id="overall-score">{own["overall"]:.2f}</span> · Season rank: {own["rank"]}</p>'
            html=html.replace('Pause time to freeze your settlement.','Season time is shared by all players.')
            html=html.replace('Your settlement starts paused. Place a Garden, assign builders, then start time. Completed Food buildings need Food workers to produce.','Season time runs automatically. Place a Garden and assign builders. Completed production buildings need workers to produce.')
            if frozen:
                html=html.replace('data-status="active"','data-status="suspended"').replace('data-status="finalizing"','data-status="suspended"').replace('Time is running.','Your settlement is frozen.')
            if state:bar+='<nav aria-label="Player interaction"><a href="#bank">Bank</a> · <a href="#rankings">Rankings</a> · <a href="#market">Market</a> · <a href="#diplomacy">Diplomacy</a> · <a href="#messages">Messages</a> · <a href="#board">Board</a></nav>'
            if frozen:bar+='<p class="error" role="status">Your settlement is frozen. This prototype freezes supply shortages before health consequences; trade for Food and Water to resume.</p>'
            if state and urlsplit(self.path).path not in ('/admin','/account'):
                html=re.sub(r'data-revision="([^"]*)"',lambda match:f'data-revision="{match[1]}{trade_revision}"',html)
                html=html.replace('</main>',trading.panel(self.server.database,state,self.form_token)+combat.panel(self.server.database,state,self.form_token,int(self.server.clock()))+market.panel(self.server.database,state,self.form_token,int(self.server.clock()))+diplomacy.panel(self.server.database,state,self.form_token,int(self.server.clock()))+communication.panel(self.server.database,state,self.form_token,int(self.server.clock()))+expansion_views.panel(self.server.database,state,self.form_token,int(self.server.clock()))+'</main>')
            html=html.replace('<main id="main">','<main id="main">'+bar);body=html.encode()
        super().reply(status,body,content_type,location)
    def do_GET(self):
        self.load_actor()
        if not self.local_request():return
        path=urlsplit(self.path).path
        if path.startswith('/static/') or path=='/favicon.ico':super().do_GET();return
        if path in ('/','/login','/register') and (not self.actor or self.actor['account_id'] is None):
            if not self.actor:self.rotate(None)
            self.reply(200,self.auth_page());return
        if not self.actor or self.actor['account_id'] is None:self.reply(401,b'Log in first.','text/plain; charset=utf-8');return
        if path=='/admin':
            try:self.reply(200,self.simple_page('Administration',admin.panel(self.server.database,self.actor['account_id'],self.form_token)))
            except PermissionError:self.reply(403,b'Administrator access required.','text/plain; charset=utf-8')
            return
        if path=='/account':self.reply(200,self.settings_page());return
        with account_scope(self.actor['account_id']):
            if path in ('/','/api/resources'):expansion.refresh(self.server.database,int(self.server.clock()))
            super().do_GET()
    def do_POST(self):
        self.load_actor()
        if not self.local_request():return
        if not self.actor:self.reply(403,b'Reload and log in before submitting.','text/plain; charset=utf-8');return
        if self.path not in ('/login','/register','/logout','/settlement','/trade','/conflict','/market','/diplomacy','/communication','/bank','/admin','/account'):
            if self.actor['account_id'] is None:self.reply(401,b'Log in first.','text/plain; charset=utf-8');return
            if self.path=='/clock':self.reply(403,b'Season time controls are unavailable to player accounts.','text/plain; charset=utf-8');return
            with account_scope(self.actor['account_id']):super().do_POST()
            return
        port=self.server.server_address[1]
        if not self.valid_origin():
            self.reply(403,b'Request origin rejected.','text/plain; charset=utf-8');return
        if self.headers.get('Content-Type','').split(';')[0]!='application/x-www-form-urlencoded':self.reply(415,b'Expected a form.','text/plain; charset=utf-8');return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=(16384 if self.path=='/communication' else 4096):self.reply(413,b'Invalid form size.','text/plain; charset=utf-8');return
            form=parse_qs(self.rfile.read(length).decode('utf-8'),max_num_fields=64 if self.path=='/conflict' else 8,keep_blank_values=True)
            if any(len(values)!=1 for key,values in form.items() if not (self.path=='/conflict' and key in ('citizen_id','drone_id'))):raise ValueError('Duplicate form fields.')
        except (ValueError,UnicodeError):self.reply(400,b'Invalid form.','text/plain; charset=utf-8');return
        if not secrets.compare_digest(form.get('token',[''])[0].encode(),self.form_token.encode()):self.reply(403,b'Reload the page first.','text/plain; charset=utf-8');return
        now=int(self.server.clock())
        try:
            if self.path=='/admin':
                def value(name):return form.get(name,[''])[0]
                admin.transact(self.server.database,self.actor['account_id'],value('action'),now,target=int(value('target')) if value('target') else None,reason=value('reason'),password=value('password'),body=value('body'),
                               settlement_id=int(value('settlement_id')) if value('settlement_id') else None,field=value('field'),
                               value=float(value('value')) if value('value') else None,
                               expected=float(value('expected')) if value('expected') else None)
                self.reply(303,location='/admin');return
            elif self.path=='/account':
                if self.actor['account_id'] is None:raise ValueError('Log in first.')
                admin.change_password(self.server.database,self.actor['account_id'],form.get('current',[''])[0],form.get('password',[''])[0],now)
                self.rotate(None)
                self.reply(303,location='/');return
            elif self.path in ('/market','/diplomacy','/communication','/bank'):
                if self.actor['account_id'] is None:raise ValueError('Log in first.')
                action=form.get('action',[''])[0]
                def value(name,default=''):return form.get(name,[default])[0]
                def integer(name):return int(value(name)) if value(name) else None
                with account_scope(self.actor['account_id']):
                    if self.path=='/bank':expansion.transact(self.server.database,action,now,amount=integer('amount'),days=integer('days'),loan_id=integer('loan_id'),investment_id=integer('investment_id'))
                    elif self.path=='/market':market.transact(self.server.database,action,now,resource=value('resource'),quantity=integer('quantity'),unit_price=integer('unit_price'),listing_id=integer('listing_id'))
                    elif self.path=='/diplomacy':diplomacy.transact(self.server.database,action,now,target_id=integer('target_id'),treaty_type=value('treaty_type'),treaty_id=integer('treaty_id'))
                    else:communication.transact(self.server.database,action,now,target_id=integer('target_id'),subject=value('subject'),body=value('body'),message_id=integer('message_id'),post_id=integer('post_id'),reason=value('reason'))
            elif self.path=='/conflict':
                if self.actor['account_id'] is None:raise ValueError('Log in first.')
                with account_scope(self.actor['account_id']):
                    combat.command(self.server.database,form.get('action',[''])[0],now,target_id=int(form.get('target_id',[''])[0]),citizen_ids=[int(cid) for cid in form.get('citizen_id',[])],objective=form.get('objective',['balanced'])[0],drone_ids=[int(uid) for uid in form.get('drone_id',[])],missile_count=int(form.get('missile_count',['0'])[0]))
            elif self.path=='/trade':
                if self.actor['account_id'] is None:raise ValueError('Log in first.')
                action=form.get('action',[''])[0]
                with account_scope(self.actor['account_id']):
                    if action=='propose':
                        trading.transact(self.server.database,action,now,recipient_id=int(form.get('recipient_id',[''])[0]),offered={form.get('offered_resource',[''])[0]:float(form.get('offered_quantity',[''])[0])},requested={form.get('requested_resource',[''])[0]:float(form.get('requested_quantity',[''])[0])})
                    else:trading.transact(self.server.database,action,now,trade_id=int(form.get('trade_id',[''])[0]))
            elif self.path=='/logout':self.rotate(None)
            elif self.path=='/settlement':
                if self.actor['account_id'] is None:raise ValueError('Log in first.')
                accounts.join(self.server.database,self.actor['account_id'],form.get('name',[''])[0],now)
            else:
                if self.actor['account_id'] is not None:raise ValueError('Log out before changing accounts.')
                username=form.get('username',[''])[0];password=form.get('password',[''])[0]
                if len(username)>24 or len(password)>128:raise ValueError('Invalid username or password.')
                if self.path=='/register':aid=accounts.register(self.server.database,username,password,now)
                else:
                    aid=accounts.authenticate(self.server.database,username,password,now)
                    if aid is None:raise ValueError('Login failed. Check your details or try again shortly.')
                self.rotate(aid)
        except PermissionError:
            self.reply(403,b'Administrator access required.','text/plain; charset=utf-8');return
        except ValueError as error:
            if self.actor['account_id'] is None:self.reply(400,self.auth_page(str(error)))
            else:self.reply(400,str(error).encode(),'text/plain; charset=utf-8')
            return
        except sqlite3.Error:self.reply(500,b'Could not save. No game data was reset.','text/plain; charset=utf-8');return
        self.reply(303,location='/')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--database',type=Path,default=ROOT/'database/accounts.db');parser.add_argument('--port',type=int,default=8767);parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--allow-host',action='append',default=[]);args=parser.parse_args()
    if not 0<=args.port<=65535:parser.error('Port must be between 0 and 65535.')
    if args.host not in ('127.0.0.1','localhost') and not args.allow_host:parser.error('Network hosting requires --allow-host with your actual LAN address.')
    try:
        allowed=[hosting.hostname(h) for h in args.allow_host]
    except ValueError as error:parser.error(str(error))
    try:
        accounts.prepare(args.database)
        with AccountServer((args.host,args.port),args.database,allowed_hosts=allowed) as server:
            for host in allowed:print(f'Players: http://{host}:{server.server_address[1]}',flush=True)
            print(f'Open http://127.0.0.1:{server.server_address[1]}\nAccount save: {server.database}',flush=True);server.serve_forever()
    except KeyboardInterrupt:pass
    except (ValueError,OSError,sqlite3.Error) as error:print(f'Could not start accounts: {error}');return 1
    return 0

if __name__=='__main__':raise SystemExit(main())

"""Account isolation, password/session behavior, shared map and HTTP authorization."""
import unittest,tempfile,sqlite3,threading,http.client,re
from contextlib import closing
from pathlib import Path
from urllib.parse import urlencode
from game import accounts
from game.settlement import account_scope,read_settlement,create_settlement,prepare_database
from game.buildings import change_building
from game.simulation import advance_settlement
from database.create_database import connect_database
from accounts_app import AccountServer

class AccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'accounts.db';accounts.prepare(self.path)
    def player(self,name='alpha'):
        aid=accounts.register(self.path,name,'test-password-long',1000);accounts.join(self.path,aid,name,1000);return aid
    def sql(self,query,args=()):
        with closing(connect_database(self.path)) as c,c:return c.execute(query,args).fetchall()
    def state(self,aid):
        with account_scope(aid):return read_settlement(self.path)
    def test_passwords_salted_login_case_normalized_and_inactive_rejected(self):
        a=self.player();b=self.player('bravo');rows=self.sql('select password_hash from accounts');self.assertNotEqual(rows[0][0],rows[1][0]);self.assertNotIn('test-password-long',str(rows))
        self.assertEqual(accounts.authenticate(self.path,'ALPHA','test-password-long',1000),a)
        self.assertIsNone(accounts.authenticate(self.path,'alpha','wrong',1000));self.sql('update accounts set is_active=0 where account_id=?',(a,));self.assertIsNone(accounts.authenticate(self.path,'alpha','test-password-long',1000))
    def test_invalid_registration_and_duplicate_case(self):
        for user,password in [('ab','test-password-long'),('bad name','test-password-long'),('alpha','short'),('__local_prototype__','test-password-long')]:
            with self.assertRaises(ValueError):accounts.register(self.path,user,password,1000)
        accounts.register(self.path,'alpha','test-password-long',1000)
        with self.assertRaises(ValueError):accounts.register(self.path,'Alpha','test-password-long',1000)
    def test_login_throttle_expires(self):
        a=self.player()
        for _ in range(5):self.assertIsNone(accounts.authenticate(self.path,'alpha','wrong',1000))
        self.assertIsNone(accounts.authenticate(self.path,'alpha','test-password-long',1001))
        self.assertEqual(accounts.authenticate(self.path,'alpha','test-password-long',1060),a)
    def test_sessions_hashed_rotated_expire_and_persist(self):
        a=self.player();token,s=accounts.new_session(self.path,a,1000);self.assertEqual(accounts.session(self.path,token,1001)['account_id'],a)
        self.assertNotEqual(token,self.sql('select token_hash from auth_sessions')[0][0]);accounts.prepare(self.path)
        self.assertIsNotNone(accounts.session(self.path,token,1001));new,_=accounts.new_session(self.path,None,1002,token);self.assertIsNone(accounts.session(self.path,token,1003));self.assertIsNone(accounts.session(self.path,new,87402))
    def test_shared_map_season_private_loot_and_bank_ledger(self):
        a=self.player();b=self.player('bravo');one=self.state(a);two=self.state(b)
        self.assertEqual(one['season']['season_id'],two['season']['season_id']);self.assertEqual(one['season']['config_version'],'prototype_v8')
        fields=('season_derelict_id','derelict_type','origin_x','origin_y')
        self.assertEqual([tuple(d[k] for k in fields) for d in one['derelicts']],[tuple(d[k] for k in fields) for d in two['derelicts']])
        self.assertNotEqual(one['derelicts'][0]['random_nonce'],two['derelicts'][0]['random_nonce'])
        self.assertEqual(len(self.sql('select * from season_derelicts')),64);self.assertEqual(self.sql('select credits from season_bank')[0][0],-1000)
        self.assertEqual(self.sql('select balance_after from credit_transactions where settlement_id is null order by transaction_id')[-1][0],-1000)
    def test_join_repeated_and_duplicate_settlement_name_roll_back(self):
        a=self.player();before=self.state(a);accounts.join(self.path,a,'different',1000);self.assertEqual(before,self.state(a))
        b=accounts.register(self.path,'bravo','test-password-long',1000)
        with self.assertRaises(ValueError):accounts.join(self.path,b,'alpha',1000)
        self.assertEqual(before,self.state(a));self.assertIsNone(self.state(b));self.assertEqual(len(self.sql('select * from settlements')),1)
    def test_foreign_worker_ids_rejected_and_owner_state_unchanged(self):
        a=self.player();b=self.player('bravo');before=self.state(b)
        with account_scope(a):
            from game.simulation import apply_action
            with self.assertRaises(ValueError):apply_action(self.path,'assign',citizen_id=before['citizens'][0]['citizen_id'],now=1000)
        self.assertEqual(before,self.state(b))
    def test_supply_shortage_freezes_only_owner(self):
        a=self.player();b=self.player('bravo');sid=self.state(a)['settlement']['settlement_id'];self.sql('update settlement_resources set food=.01 where settlement_id=?',(sid,))
        with account_scope(a):one=advance_settlement(self.path,now=1060)
        self.assertEqual(one['settlement']['status'],'suspended');self.assertEqual(one['season']['status'],'active')
        with account_scope(b):two=advance_settlement(self.path,now=1060)
        self.assertEqual(two['settlement']['status'],'active');self.assertGreater(two['citizens'][0]['xp'],0)
    def test_context_isolation_and_reset(self):
        a=self.player();b=self.player('bravo');results=[]
        def run(aid):
            with account_scope(aid):results.append(read_settlement(self.path)['settlement']['account_id'])
        threads=[threading.Thread(target=run,args=(aid,)) for aid in (a,b)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(sorted(results),[a,b])
        with self.assertRaises(ValueError):read_settlement(self.path)
    def test_local_save_refused_without_mutation(self):
        p=Path(self.tmp.name)/'local.db';prepare_database(p);create_settlement(p,'Local',now=1000);before=p.read_bytes()
        with self.assertRaises(ValueError):accounts.prepare(p)
        self.assertEqual(before,p.read_bytes())
    def test_finished_season_rejects_join(self):
        self.player();b=accounts.register(self.path,'bravo','test-password-long',1000);self.sql("update seasons set status='finished'")
        with self.assertRaises(ValueError):accounts.join(self.path,b,'bravo',1000)
        self.assertEqual(len(self.sql('select * from settlements')),1)

    def test_late_join_preserves_existing_health_xp_and_loot(self):
        a=self.player();self.sql('update citizens set current_hp=75,xp=10 where citizen_id=2');before=self.state(a)
        b=accounts.register(self.path,'bravo','test-password-long',1100);accounts.join(self.path,b,'bravo',1100)
        after=self.state(a)
        for key in ('citizens','resources','derelicts','jobs','recovery_clock','xp_clock'):self.assertEqual(before[key],after[key])
        self.assertEqual(self.state(b)['settlement']['simulation_processed_at'],1100)

class AccountHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'accounts.db';accounts.prepare(self.path);self.now=1000
        self.server=AccountServer(('127.0.0.1',0),self.path,clock=lambda:self.now);self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':0.01},daemon=True);self.thread.start();self.addCleanup(self.stop)
    def stop(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def request(self,method='GET',path='/',fields=None,cookie='',headers=None):
        client=http.client.HTTPConnection(*self.server.server_address);h={'Cookie':cookie}
        body=urlencode(fields) if fields is not None else None
        if body is not None:h['Content-Type']='application/x-www-form-urlencoded'
        h.update(headers or {});client.request(method,path,body,h);r=client.getresponse();result=(r.status,dict(r.getheaders()),r.read().decode());client.close();return result
    def anonymous(self):
        status,h,html=self.request();return h['Set-Cookie'].split(';')[0],re.search('name="token" value="([^"]+)"',html)[1]
    def player(self,name):
        cookie,csrf=self.anonymous();status,h,_=self.request('POST','/register',{'username':name,'password':'test-password-long','token':csrf},cookie);self.assertEqual(status,303);cookie=h['Set-Cookie'].split(';')[0]
        _,_,html=self.request(cookie=cookie);csrf=re.search('name="token" value="([^"]+)"',html)[1]
        self.assertEqual(self.request('POST','/settlement',{'name':name,'token':csrf},cookie)[0],303);return cookie,csrf
    def test_register_login_logout_session_rotation_and_no_clock_controls(self):
        cookie,csrf=self.player('alpha');_,_,html=self.request(cookie=cookie);self.assertIn('Logged in as alpha',html);self.assertNotIn('action="/clock"',html)
        status,h,_=self.request('POST','/logout',{'token':csrf},cookie);self.assertEqual(status,303);self.assertEqual(self.request(path='/api/resources',cookie=cookie)[0],401)
        anon=h['Set-Cookie'].split(';')[0];_,_,html=self.request(cookie=anon);token=re.search('name="token" value="([^"]+)"',html)[1]
        status,h,_=self.request('POST','/login',{'username':'alpha','password':'test-password-long','token':token},anon);self.assertEqual(status,303);self.assertNotEqual(h['Set-Cookie'].split(';')[0],cookie)
        self.assertIn('HttpOnly',h['Set-Cookie']);self.assertIn('SameSite=Strict',h['Set-Cookie'])
    def test_two_users_only_see_own_settlement_and_csrf(self):
        a,tokena=self.player('alpha');b,tokenb=self.player('bravo')
        self.assertIn('<h1>alpha</h1>',self.request(cookie=a)[2]);self.assertNotIn('<h1>bravo</h1>',self.request(cookie=a)[2])
        self.assertEqual(self.request('POST','/administrator',{'citizen_id':7,'token':tokena},a)[0],400)
        self.assertEqual(self.request('POST','/administrator',{'citizen_id':1,'token':tokenb},a)[0],403)
        self.assertEqual(self.request('POST','/clock',{'action':'pause','token':tokena},a)[0],403)
        self.assertEqual(self.request(path='/api/resources',cookie=b)[0],200)
    def test_unauthenticated_csrf_origin_and_expiry(self):
        self.assertEqual(self.request(path='/api/resources')[0],401)
        cookie,csrf=self.anonymous()
        self.assertEqual(self.request('POST','/register',{'username':'alpha','password':'test-password-long','token':'wrong'},cookie)[0],403)
        self.assertEqual(self.request('POST','/register',{'username':'alpha','password':'test-password-long','token':csrf},cookie,{'Origin':'https://foreign.invalid'})[0],403)
        a,_=self.player('alpha');self.now=87400;self.assertEqual(self.request(path='/api/resources',cookie=a)[0],401)
    def test_private_paths_and_forged_identity_ignored(self):
        a,token=self.player('alpha')
        for path in ('/database/accounts.db','/game/accounts.py','/static/../accounts_app.py'):self.assertEqual(self.request(path=path,cookie=a)[0],404)
        self.assertEqual(self.request('POST','/settlement',{'name':'other','token':token,'account_id':999},a)[0],303)
        self.assertEqual(len(accounts.session(self.path,a.split('=',1)[1],1000)['username']),5)

    def test_foreign_buildings_and_derelicts_rejected(self):
        a,token=self.player('alpha');b,_=self.player('bravo')
        self.assertEqual(self.request('POST','/buildings',{'token':token,'action':'upgrade','building_id':2,'expected_level':1},a)[0],400)
        self.assertEqual(self.request('POST','/scavenging',{'token':token,'action':'assign','derelict_id':65,'citizen_id':2},a)[0],400)
        self.assertEqual(self.request(path='/api/resources',cookie=b)[0],200)
    def test_authenticated_session_survives_server_restart(self):
        cookie,token=self.player('alpha');self.stop()
        self.server=AccountServer(('127.0.0.1',0),self.path,clock=lambda:self.now);self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':0.01},daemon=True);self.thread.start()
        self.assertEqual(self.request(path='/api/resources',cookie=cookie)[0],200)
        self.assertIn('Logged in as alpha',self.request(cookie=cookie)[2])

    def test_supply_freeze_visible_without_reloading_forever(self):
        cookie,csrf=self.player('alpha')
        with closing(connect_database(self.path)) as c,c:c.execute('update settlement_resources set food=.01')
        self.now=1060
        status,_,body=self.request(path='/api/resources',cookie=cookie)
        import json
        self.assertEqual(json.loads(body)['status'],'suspended')
        html=self.request(cookie=cookie)[2];self.assertIn('data-status="suspended"',html);self.assertIn('Your settlement is frozen.',html)

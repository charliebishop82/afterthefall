"""Independent operator transport and diagnostic safety, on disposable databases."""
from contextlib import closing
from pathlib import Path
import re
import tempfile
import unittest

from admin_suite import create_app, COOKIE
from database.create_database import connect_database
from flask_app import create_app as game_app, COOKIE as GAME_COOKIE
from game import accounts, admin, diagnostics, lobby


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'playtest.db'; lobby.prepare(self.path)
        self.owner=accounts.register(self.path,'owner','owner-password-long',1000)
        self.player=accounts.register(self.path,'player','player-password-long',1000)
        admin.grant(self.path,'owner',1000)
        self.log=Path(self.tmp.name)/'operator.log'
        self.app=create_app(self.path,clock=lambda:1000,log_path=self.log)
        self.addCleanup(lambda:[h.close() for h in self.app.extensions['operator_logger'].handlers])
        self.client=self.app.test_client(); self.base='http://127.0.0.1:8768'

    def get(self,path='/'): return self.client.get(path,base_url=self.base)
    def post(self,path,fields,**kwargs): return self.client.post(path,data=fields,base_url=self.base,**kwargs)
    def login(self,name='owner'):
        page=self.get('/login')
        token=re.search('name="token" value="([^"]+)"',page.text)[1]
        response=self.post('/login',{'token':token,'username':name,'password':name+'-password-long'})
        return response
    def csrf(self): return accounts.session(self.path,self.client.get_cookie(COOKIE,domain='127.0.0.1').value,1000)['csrf']

    def test_separate_login_admin_without_settlement(self):
        self.assertEqual(self.get().status_code,303)
        self.assertEqual(self.login().status_code,303)
        self.assertEqual(self.get().status_code,200)
        with closing(connect_database(self.path)) as c: self.assertEqual(c.execute('SELECT count(*) FROM settlements').fetchone()[0],0)
        self.assertNotEqual(COOKIE,GAME_COOKIE)
        self.assertIsNone(self.client.get_cookie(GAME_COOKIE,domain='127.0.0.1'))

    def test_player_credentials_cannot_access_console(self):
        self.assertEqual(self.login('player').status_code,403)
        self.assertEqual(self.get('/diagnostics').status_code,303)
        token,_=accounts.new_session(self.path,self.player,1000)
        self.client.set_cookie(COOKIE,token,domain='127.0.0.1')
        self.assertEqual(self.get('/logs').status_code,403)

    def test_player_server_rejects_operator_writes_even_for_admin(self):
        player=game_app(self.path,clock=lambda:1000).test_client()
        token,session=accounts.new_session(self.path,self.owner,1000)
        player.set_cookie(GAME_COOKIE,token,domain='127.0.0.1')
        for route in ('/admin','/lobby'):
            self.assertEqual(player.post(route,data={'token':session['csrf'],'action':'start','reason':'test'},base_url='http://127.0.0.1:8767').status_code,403)
        self.assertNotIn('Start playtest for all',player.get('/',base_url='http://127.0.0.1:8767').text)
        self.assertEqual(lobby.status(self.path)['status'],'waiting')

    def test_host_origin_csrf_and_duplicate_fields(self):
        self.login()
        self.assertEqual(self.client.get('/diagnostics',base_url='http://evil.invalid').status_code,403)
        self.assertEqual(self.post('/lobby',{'token':'bad','reason':'test'}).status_code,403)
        self.assertEqual(self.post('/lobby',{'token':self.csrf(),'reason':'test'},headers={'Origin':'https://evil.invalid'}).status_code,403)
        self.assertEqual(self.post('/lobby','token='+self.csrf()+'&reason=one&reason=two',content_type='application/x-www-form-urlencoded').status_code,400)

    def test_launch_from_console_and_player_observes_same_save(self):
        self.login(); lobby.enroll(self.path,self.player,'Player town',1000)
        self.assertEqual(self.post('/lobby',{'token':self.csrf(),'reason':'test shared launch'}).status_code,303)
        self.assertEqual(lobby.status(self.path)['status'],'started')
        player=game_app(self.path,clock=lambda:1000).test_client()
        token,_=accounts.new_session(self.path,self.player,1000); player.set_cookie(GAME_COOKIE,token,domain='127.0.0.1')
        self.assertIn('Player town',player.get('/',base_url='http://127.0.0.1:8767').text)

    def test_diagnostics_read_only_and_missing_resource_detection(self):
        lobby.enroll(self.path,self.player,'Player town',1000); lobby.start(self.path,self.owner,1000,'test')
        before=self.path.read_bytes(); report=diagnostics.inspect(self.path)
        self.assertTrue(report['ok'],report); self.assertEqual(self.path.read_bytes(),before)
        with closing(connect_database(self.path)) as c,c: c.execute('DELETE FROM settlement_resources')
        before=self.path.read_bytes(); report=diagnostics.inspect(self.path)
        self.assertIn('Missing resources',[r[1] for r in report['findings']]); self.assertEqual(self.path.read_bytes(),before)

    def test_reservation_over_stock_and_closed_offer_detection(self):
        lobby.enroll(self.path,self.player,'Player town',1000); lobby.start(self.path,self.owner,1000,'test')
        with closing(connect_database(self.path)) as c,c:
            c.execute("INSERT INTO market_listings(season_id,seller_settlement_id,resource_type,original_quantity,remaining_quantity,unit_price,status,created_at) VALUES (1,1,'metal',1,1,1,'cancelled',1000)")
            c.execute("INSERT INTO resource_reservations(settlement_id,resource_type,quantity,market_listing_id,created_at) VALUES (1,'metal',99999,1,1000)")
        names=[r[1] for r in diagnostics.inspect(self.path)['findings']]
        self.assertIn('Reserved stock',names); self.assertIn('Stale reservation',names)

    def test_logs_escape_and_do_not_record_credentials(self):
        self.login()
        lobby.enroll(self.path,self.player,'Player town',1000); lobby.start(self.path,self.owner,1000,'test')
        with closing(connect_database(self.path)) as c,c:
            c.execute("INSERT INTO game_events(season_id,event_type,occurred_at,event_data) VALUES (1,'example',1000,?)",('{"text":"<script>bad</script>"}',))
        response=self.get('/logs')
        self.assertIn('&lt;script&gt;',response.text); self.assertNotIn('<script>bad',response.text)
        self.assertNotIn('owner-password-long',self.log.read_text())
        self.assertNotIn(self.csrf(),self.log.read_text())
        self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_logout_only_revokes_console_session(self):
        self.login(); player_token,_=accounts.new_session(self.path,self.owner,1000)
        old=self.client.get_cookie(COOKIE,domain='127.0.0.1').value
        self.assertEqual(self.post('/logout',{'token':self.csrf()}).status_code,303)
        self.assertIsNone(accounts.session(self.path,old,1000)); self.assertIsNotNone(accounts.session(self.path,player_token,1000))

    def test_local_operator_creation_validates_and_audits_without_enrollment(self):
        for name,password in (('bad name','new-operator-password'),('newadmin','short')):
            with self.assertRaises(ValueError): admin.create_operator(self.path,name,password,1000)
        aid=admin.create_operator(self.path,'newadmin','new-operator-password',1000)
        self.assertEqual(accounts.authenticate(self.path,'newadmin','new-operator-password',1000),aid)
        with self.assertRaises(ValueError): admin.create_operator(self.path,'newadmin','replacement-password',1000)
        with closing(connect_database(self.path)) as c:
            self.assertEqual(c.execute('SELECT is_admin FROM accounts WHERE account_id=?',(aid,)).fetchone()[0],1)
            self.assertEqual(c.execute("SELECT count(*) FROM admin_actions WHERE action_type='local_admin_create'").fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM playtest_members').fetchone()[0],0)
            self.assertNotIn('new-operator-password',c.execute("SELECT after_values FROM admin_actions WHERE action_type='local_admin_create'").fetchone()[0])


if __name__=='__main__': unittest.main()

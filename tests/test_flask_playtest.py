"""Flask transport and atomic shared launch, using disposable saves and clocks."""
from contextlib import closing
import http.client
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from database.create_database import connect_database
from tests.fixtures import FlaskFixture,restore_case_baseline
from flask_app import COOKIE, GAME_ROUTES, create_app, game_action, public_origin
from game import accounts, admin, lobby
from game.settlement import account_scope, read_settlement
from serve_game import server_options


class PlaytestTests(unittest.TestCase):
    def setUp(self):
        restore_case_baseline(self,'waiting-lobby',PlaytestTests.prepare_world)

    def prepare_world(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'playtest.db'
        lobby.prepare(self.path)
        self.owner = accounts.register(self.path, 'owner', 'owner-password-long', 1000)
        self.player = accounts.register(self.path, 'player', 'player-password-long', 1000)
        admin.grant(self.path, 'owner', 1000)

    def sql(self, query, args=()):
        with closing(connect_database(self.path)) as c, c:
            return c.execute(query, args).fetchall()

    def enroll(self):
        lobby.enroll(self.path, self.owner, 'Owner town', 1001)
        lobby.enroll(self.path, self.player, 'Player town', 9000)

    def state(self, aid):
        with account_scope(aid):return read_settlement(self.path)

    def test_waiting_has_no_game_state_and_survives_prepare(self):
        self.enroll(); lobby.prepare(self.path)
        self.assertEqual(lobby.status(self.path)['status'], 'waiting')
        self.assertEqual(self.sql('SELECT count(*) FROM seasons'), [(0,)])
        self.assertEqual(self.sql('SELECT count(*) FROM settlements'), [(0,)])
        self.assertEqual(len(lobby.status(self.path)['members']), 2)

    def test_existing_save_refused_without_changes(self):
        old = Path(self.tmp.name)/'old.db'; accounts.prepare(old)
        aid = accounts.register(old, 'legacy', 'legacy-password-long', 1000)
        accounts.join(old, aid, 'Legacy', 1000)
        before = old.read_bytes()
        with self.assertRaises(ValueError):lobby.prepare(old)
        self.assertEqual(before, old.read_bytes())

    def test_names_validated_unique_and_can_be_changed(self):
        self.enroll()
        with self.assertRaises(ValueError):lobby.enroll(self.path, self.player, 'Owner town', 9001)
        for name in ('', 'x'*41, 'bad\nname'):
            with self.assertRaises(ValueError):lobby.enroll(self.path, self.player, name, 9001)
        lobby.enroll(self.path, self.player, 'Renamed', 9002)
        self.assertEqual(lobby.status(self.path)['members'][1]['settlement_name'], 'Renamed')
        with self.assertRaises(PermissionError):lobby.enroll(self.path, 999, 'Other', 9002)

    def test_start_requires_admin_reason_and_enrollment(self):
        with self.assertRaises(PermissionError):lobby.start(self.path, self.player, 10000, 'launch')
        with self.assertRaises(ValueError):lobby.start(self.path, self.owner, 10000, 'launch')
        self.enroll()
        with self.assertRaises(ValueError):lobby.start(self.path, self.owner, 10000, '')
        self.assertEqual(self.sql('SELECT count(*) FROM seasons'), [(0,)])

    def test_atomic_shared_start_equal_resources_and_all_features(self):
        self.enroll(); self.assertEqual(lobby.start(self.path, self.owner, 10000, 'ready'), 2)
        one, two = self.state(self.owner), self.state(self.player)
        self.assertEqual({k:v for k,v in one['resources'].items() if k!='settlement_id'}, {k:v for k,v in two['resources'].items() if k!='settlement_id'})
        for state in (one, two):
            self.assertEqual(state['season']['started_at'], 10000)
            self.assertEqual(state['settlement']['simulation_processed_at'], 10000)
            self.assertEqual(state['season']['config_version'], 'prototype_v13')
            self.assertTrue(state['expansion'])
            self.assertIn('consequences', state['config'])
            self.assertIsNotNone(state['needs_clock'])
        self.assertEqual(one['settlement']['protection_until'], two['settlement']['protection_until'])
        self.assertEqual(self.sql("SELECT count(*) FROM game_events WHERE event_type='bank_reserve_funded'"), [(2,)])
        self.assertEqual(self.sql("SELECT count(*) FROM admin_actions WHERE action_type='playtest_start'"), [(1,)])
        lobby.prepare(self.path)
        self.assertEqual(lobby.status(self.path)['started_at'], 10000)
        with self.assertRaises(ValueError):lobby.start(self.path, self.owner, 10001, 'again')
        with self.assertRaises(ValueError):lobby.enroll(self.path, self.player, 'Late', 10001)
        self.assertEqual(one, self.state(self.owner))

    def test_partial_failure_rolls_back_entire_launch(self):
        self.enroll(); original = accounts.join_in_transaction
        def fail_second(c, aid, name, now):
            if aid == self.player:raise ValueError('injected failure')
            return original(c, aid, name, now)
        with patch('game.accounts.join_in_transaction', side_effect=fail_second):
            with self.assertRaises(ValueError):lobby.start(self.path, self.owner, 10000, 'ready')
        for table in ('seasons', 'settlements', 'citizens', 'season_derelicts'):
            self.assertEqual(self.sql(f'SELECT count(*) FROM {table}'), [(0,)])
        self.assertEqual(lobby.status(self.path)['status'], 'waiting')
        self.assertEqual(lobby.start(self.path, self.owner, 10000, 'retry'), 2)

    def test_suspended_enrollment_not_seeded(self):
        self.enroll()
        admin.transact(self.path, self.owner, 'suspend', 9001, target=self.player, reason='test')
        with self.assertRaises(PermissionError):lobby.enroll(self.path, self.player, 'Other', 9002)
        self.assertEqual(lobby.start(self.path, self.owner, 10000, 'ready'), 1)
        self.assertIsNone(self.state(self.player))


class FlaskTests(FlaskFixture, unittest.TestCase):
    def test_rejected_building_release_keeps_game_interface(self):
        token=self.launch()
        with closing(connect_database(self.path)) as c:
            citizen=c.execute('SELECT citizen_id FROM citizens ORDER BY citizen_id LIMIT 1').fetchone()[0]
            building=c.execute('SELECT building_id FROM buildings ORDER BY building_id LIMIT 1').fetchone()[0]
            before=c.execute('SELECT count(*) FROM citizen_assignments').fetchone()[0]
        response=self.post('/buildings',dict(token=token,action='release',citizen_id=citizen,building_id=building))
        self.assertEqual(response.status_code,400)
        self.assertEqual(response.mimetype,'text/html')
        self.assertIn('That citizen is not assigned to this building.',response.text)
        self.assertIn('role="alert"',response.text)
        self.assertIn('id="main"',response.text)
        self.assertIn('/static/player-ui.js',response.text)
        self.assertIn('Settlement / lobby',response.text)
        with closing(connect_database(self.path)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM citizen_assignments').fetchone()[0],before)

    def test_action_error_escapes_message_and_does_not_replay_action(self):
        token=self.launch()
        with patch('flask_app.game_action',side_effect=ValueError('<script>bad()</script>')) as action:
            response=self.post('/buildings',dict(token=token,action='release'))
        self.assertEqual(response.status_code,400)
        self.assertIn('&lt;script&gt;bad()&lt;/script&gt;',response.text)
        self.assertNotIn('<script>bad()</script>',response.text)
        action.assert_called_once()

    def test_waiting_render_and_game_routes_do_not_advance_time(self):
        token = self.player('owner'); self.now = 80000
        self.assertIn('No game time runs', self.get().text)
        self.assertEqual(self.get(path='/api/resources').json, {'status':'waiting'})
        for route in GAME_ROUTES:
            self.assertEqual(self.post(route, {'token':token, 'action':'enable'}).status_code, 403, route)
        self.assertEqual(self.post('/clock', {'token':token, 'action':'resume'}).status_code, 403)
        with closing(connect_database(self.path)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM seasons').fetchone()[0], 0)

    def test_registration_cannot_grant_admin_and_launch_denied(self):
        token = self.player('owner')
        self.assertEqual(self.get(path='/admin').status_code, 403)
        self.assertEqual(self.console_post('/lobby', {'token':token, 'action':'start', 'reason':'ready'}).status_code, 403)
        self.assertNotIn('Start playtest for all', self.get().text)

    def test_logout_login_rotates_cookie_and_revokes_old_session(self):
        token = self.player('owner'); old = self.client.get_cookie(COOKIE, domain='127.0.0.1').value
        result = self.post('/logout', {'token':token})
        self.assertEqual(result.status_code, 303)
        self.assertIsNone(accounts.session(self.path, old, self.now))
        self.assertEqual(self.get(path='/api/resources').status_code, 401)
        token = re.search('name="token" value="([^"]+)"', self.get().text)[1]
        self.assertEqual(self.post('/login', {'token':token, 'username':'owner', 'password':'test-password-long'}).status_code, 303)
        self.assertNotEqual(self.client.get_cookie(COOKIE, domain='127.0.0.1').value, old)
        self.assertIn('HttpOnly', result.headers['Set-Cookie'])
        self.assertIn('SameSite=Strict', result.headers['Set-Cookie'])

    def test_password_change_revokes_other_sessions(self):
        token = self.player('owner')
        other, _ = accounts.new_session(self.path, 1, self.now)
        self.assertEqual(self.post('/account', {'token':token, 'current':'wrong', 'password':'replacement-password'}).status_code, 400)
        self.assertIsNotNone(accounts.session(self.path, other, self.now))
        self.assertEqual(self.post('/account', {'token':token, 'current':'test-password-long', 'password':'replacement-password'}).status_code, 303)
        self.assertIsNone(accounts.session(self.path, other, self.now))
        self.assertEqual(self.get(path='/api/resources').status_code, 401)

    def test_host_origin_csrf_duplicate_fields_and_size_rejected(self):
        token = self.player('owner')
        self.assertEqual(self.client.get('/', base_url='http://evil.invalid').status_code, 403)
        self.assertEqual(self.post('/settlement', {'token':'wrong', 'name':'new'}).status_code, 403)
        self.assertEqual(self.post('/settlement', {'token':token, 'name':'new'}, headers={'Origin':'https://evil.invalid'}).status_code, 403)
        raw = urlencode([('token',token), ('name','first'), ('name','second')])
        self.assertEqual(self.post('/settlement', raw, content_type='application/x-www-form-urlencoded').status_code, 400)
        self.assertEqual(self.post('/settlement', {'token':token, 'name':'x'*4100}).status_code, 413)
        self.assertEqual(self.post('/settlement', '{}', content_type='application/json').status_code, 415)
        self.assertEqual(self.post('/unknown', {'token':token}).status_code, 404)
        for path in ('/database/playtest.db', '/game/accounts.py', '/static/../flask_app.py'):
            self.assertIn(self.get(path=path).status_code, (404,405))

    def test_started_html_api_and_account_isolation(self):
        token = self.player('owner'); other = self.app.test_client(); other_token = self.player('other', other)
        admin.grant(self.path, 'owner', self.now)
        self.assertEqual(self.console_post('/lobby', {'token':token, 'action':'start', 'reason':'ready'}).status_code, 303)
        page = self.get(); self.assertEqual(page.status_code, 200)
        self.assertIn('<h1>owner</h1>', page.text); self.assertNotIn('action="/clock"', page.text)
        for anchor in ('id="bank"', 'id="market"', 'id="messages"', 'id="rankings"'):
            self.assertIn(anchor, page.text)
        data = self.get(path='/api/resources').json
        for key in ('food','water','rates','materials','revision','scores','own_score','raid_timers','trade_available'):
            self.assertIn(key, data)
        self.assertEqual(self.get(path='/api/lobby').json['status'], 'started')
        self.assertIn('<h1>other</h1>', self.get(other).text)
        with account_scope(2):before = read_settlement(self.path)
        foreign = before['citizens'][0]['citizen_id']
        self.assertEqual(self.post('/administrator', {'token':token, 'citizen_id':foreign}).status_code, 400)
        self.assertEqual(self.post('/administrator', {'token':other_token, 'citizen_id':foreign}).status_code, 403)
        with account_scope(2):self.assertEqual(before, read_settlement(self.path))

    def test_game_service_actions_and_persistence_across_restart(self):
        token = self.launch()
        self.assertEqual(self.post('/needs', {'token':token, 'action':'rations', 'food':'reduced', 'water':'full'}).status_code, 303)
        self.assertEqual(self.post('/communication', {'token':token, 'action':'post', 'body':'Ready for playtesting'}).status_code, 303)
        recreated = create_app(self.path, clock=lambda:self.now)
        client = recreated.test_client(); client.set_cookie(COOKIE, self.client.get_cookie(COOKIE, domain='127.0.0.1').value, domain='127.0.0.1')
        response = self.get(client); self.assertEqual(response.status_code, 200)
        self.assertIn('Ready for playtesting', response.text)
        self.assertEqual(lobby.status(self.path)['status'], 'started')

    def test_suspension_revokes_flask_access(self):
        token = self.player('owner'); other = self.app.test_client(); self.player('other', other)
        admin.grant(self.path, 'owner', self.now)
        result = self.console_post('/admin', {'token':token, 'action':'suspend', 'target':'2', 'reason':'test suspension'})
        self.assertEqual(result.status_code, 303)
        self.assertEqual(self.get(other, '/api/resources').status_code, 401)
        self.assertEqual(self.get(path='/admin').status_code, 200)

    def test_real_market_trade_and_diplomacy_forms(self):
        token = self.player('owner'); other = self.app.test_client(); peer = self.player('other', other)
        admin.grant(self.path, 'owner', self.now)
        self.assertEqual(self.console_post('/lobby', {'token':token,'action':'start','reason':'ready'}).status_code,303)
        # Listings were explicitly replaced; stale forms must still be rejected.
        self.assertEqual(self.post('/market', {'token':token,'action':'list','resource':'metal','quantity':'2','unit_price':'3'}).status_code,400)
        self.assertEqual(self.post('/market', {'token':token,'action':'sell','resource':'metal','quantity':'2'}).status_code,303)
        self.assertEqual(self.post('/market', {'token':peer,'action':'cancel','listing_id':'1'}, other).status_code,400)
        self.assertEqual(self.post('/market', {'token':peer,'action':'buy','resource':'metal','quantity':'1'}, other).status_code,303)
        self.assertEqual(self.post('/trade', {'token':token,'action':'propose','recipient_id':'2','offered_resource':'scrap','offered_quantity':'2','requested_resource':'metal','requested_quantity':'1'}).status_code,303)
        self.assertEqual(self.post('/trade', {'token':peer,'action':'accept','trade_id':'1'}, other).status_code,303)
        self.assertEqual(self.post('/diplomacy', {'token':token,'action':'propose','target_id':'2','treaty_type':'trade_agreement'}).status_code,303)
        self.assertEqual(self.post('/diplomacy', {'token':peer,'action':'accept','treaty_id':'1'}, other).status_code,303)
        with closing(connect_database(self.path)) as c:
            self.assertEqual(c.execute('SELECT credits FROM settlement_resources WHERE settlement_id=1').fetchone()[0],507)
            self.assertEqual(c.execute('SELECT credits FROM settlement_resources WHERE settlement_id=2').fetchone()[0],494)
            self.assertEqual(c.execute("SELECT quantity FROM market_pool_stock WHERE resource='metal'").fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM market_pool_trades').fetchone()[0],2)
            self.assertEqual(c.execute("SELECT sum(amount) FROM credit_transactions WHERE transfer_ref LIKE 'market-pool:%'").fetchone()[0],0)
            self.assertEqual(c.execute('SELECT status FROM treaties').fetchone()[0],'active')

    def test_late_registered_account_can_enroll_then_play(self):
        # Agreed rule change: active-season joins now use the normal starting seed.
        self.launch(); other = self.app.test_client(); token = self.player('late', other, enroll=False)
        self.assertEqual(self.get(other, '/api/resources').status_code, 403)
        self.assertIn('Join season', self.get(other).text)
        self.assertEqual(self.post('/settlement', {'token':token, 'name':'Late'}, other).status_code, 303)
        self.assertEqual(self.get(other, '/api/resources').status_code, 200)

    def test_public_origin_requires_https_secure_cookie_and_explicit_host(self):
        app = create_app(self.path, clock=lambda:self.now, public_url='https://test.ngrok.app')
        client = app.test_client()
        self.assertEqual(client.get('/', base_url='http://test.ngrok.app').status_code, 403)
        self.assertEqual(client.get('/', base_url='https://unknown.ngrok.app').status_code, 403)
        response = client.get('/', base_url='https://test.ngrok.app')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Secure', response.headers['Set-Cookie'])
        self.assertEqual(client.get('/', base_url='http://test.ngrok.app', headers={'X-Forwarded-Proto':'https'}).status_code, 403)
        for value in ('http://test.ngrok.app','https://test.ngrok.app/path','https://user:pass@test.ngrok.app','https://test.ngrok.app?key=secret'):
            with self.assertRaises(ValueError):public_origin(value)

    def test_repeated_combat_participants_and_construction_flags_preserved(self):
        token = self.launch()
        with patch('game.combat.command') as command:
            fields = [('token',token),('action','raid'),('citizen_id','2'),('citizen_id','3'),('drone_id','4'),('drone_id','5'),('missile_count','2'),('target_id','9')]
            self.assertEqual(self.post('/conflict', urlencode(fields), content_type='application/x-www-form-urlencoded').status_code, 303)
            self.assertEqual(command.call_args.kwargs['citizen_ids'], [2,3])
            self.assertEqual(command.call_args.kwargs['drone_ids'], [4,5])
            self.assertEqual(command.call_args.kwargs['missile_count'], 2)
        with patch('game.buildings.change_building') as change:
            self.assertEqual(self.post('/buildings', {'token':token, 'action':'upgrade', 'building_id':'1', 'expected_level':'2', 'exposed':'1'}).status_code, 303)
            self.assertEqual(change.call_args.kwargs['expected_level'], 2)
            self.assertTrue(change.call_args.kwargs['exposed'])


    def test_player_communication_rejects_moderation_even_for_admin(self):
        token=self.launch()
        self.assertEqual(self.post('/communication',{'token':token,'action':'post','body':'Public hello'}).status_code,303)
        with closing(connect_database(self.path)) as c:
            pid=c.execute('SELECT post_id FROM board_posts').fetchone()[0]
        for action in ('hide','restore'):
            response=self.post('/communication',{'token':token,'action':action,'post_id':str(pid),'reason':'operator request'})
            self.assertEqual(response.status_code,400)
        with closing(connect_database(self.path)) as c:
            self.assertEqual(c.execute('SELECT moderation_status FROM board_posts WHERE post_id=?',(pid,)).fetchone()[0],'visible')
        self.assertNotIn('Moderate post',self.get().text)
        self.assertEqual(self.console_post('/admin',{'action':'hide_post','target':str(pid),'reason':'operator request'}).status_code,303)
        self.assertNotIn('Public hello',self.get().text)
        self.assertEqual(self.console_post('/admin',{'action':'restore_post','target':str(pid),'reason':'operator request'}).status_code,303)
        self.assertIn('Public hello',self.get().text)


class WaitressTests(unittest.TestCase):
    def test_tunnel_options_only_trust_local_scheme_and_reject_public_bind(self):
        options = server_options('127.0.0.1',8767,'https://test.ngrok.app')
        self.assertEqual(options['trusted_proxy_headers'], {'x-forwarded-proto'})
        self.assertEqual(options['trusted_proxy'], '127.0.0.1')
        self.assertTrue(options['clear_untrusted_proxy_headers'])
        with self.assertRaises(ValueError):server_options('0.0.0.0',8767,'https://test.ngrok.app')
        with self.assertRaises(ValueError):server_options('127.0.0.1',0)

    def test_real_waitress_proxy_scheme_and_host_boundaries(self):
        from waitress.server import create_server
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(Path(tmp)/'test.db', clock=lambda:1000, public_url='https://test.ngrok.app')
            options = server_options('127.0.0.1',8767,'https://test.ngrok.app'); options['port'] = 0
            server = create_server(app, **options)
            thread = threading.Thread(target=server.run, daemon=True); thread.start()
            def request(headers):
                client = http.client.HTTPConnection('127.0.0.1',int(server.effective_port),timeout=5)
                try:
                    client.request('GET','/',headers=headers); response = client.getresponse(); response.read()
                    return response.status, dict(response.getheaders())
                finally:client.close()
            try:
                self.assertEqual(request({'Host':'test.ngrok.app'})[0],403)
                status, headers = request({'Host':'test.ngrok.app','X-Forwarded-Proto':'https'})
                self.assertEqual(status,200); self.assertIn('Secure', headers['Set-Cookie'])
                self.assertEqual(request({'Host':'evil.invalid','X-Forwarded-Host':'test.ngrok.app','X-Forwarded-Proto':'https'})[0],403)
            finally:
                server.task_dispatcher.shutdown(); server.close(); thread.join(timeout=5)

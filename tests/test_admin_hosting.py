"""Admin authorization, revocation, audit, LAN boundaries and restore safety."""
from contextlib import closing, redirect_stdout
import io
import http.client
from pathlib import Path
import re
import tempfile
import threading
import unittest
from urllib.parse import urlencode

from accounts_app import AccountServer
from database.create_database import connect_database
from game import accounts, admin
from manage import backup, restore, main


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'accounts.db'; accounts.prepare(self.path)
        self.owner = accounts.register(self.path, 'owner', 'owner-password-long', 1000)
        self.player = accounts.register(self.path, 'player', 'player-password-long', 1000)
        admin.grant(self.path, 'owner', 1000)

    def sql(self, query, args=()):
        with closing(connect_database(self.path)) as c, c:
            return c.execute(query, args).fetchall()

    def test_grant_is_explicit_idempotent_and_audited(self):
        self.assertEqual(self.sql('SELECT is_admin FROM accounts WHERE account_id=?', (self.player,)), [(0,)])
        admin.grant(self.path, 'OWNER', 1001)
        self.assertEqual(self.sql('SELECT count(*) FROM admin_actions'), [(1,)])
        with self.assertRaises(ValueError): admin.grant(self.path, 'missing', 1001)

    def test_nonadmin_cannot_read_or_mutate(self):
        with self.assertRaises(PermissionError): admin.panel(self.path, self.player, 'token')
        with self.assertRaises(PermissionError): admin.transact(self.path, self.player, 'suspend', 1001, target=self.owner, reason='test')
        self.assertEqual(self.sql('SELECT sum(is_active) FROM accounts'), [(2,)])

    def test_suspend_revokes_sessions_reactivation_does_not_restore_them(self):
        token, _ = accounts.new_session(self.path, self.player, 1000)
        admin.transact(self.path, self.owner, 'suspend', 1001, target=self.player, reason='test suspension')
        self.assertIsNone(accounts.session(self.path, token, 1002))
        self.assertIsNone(accounts.authenticate(self.path, 'player', 'player-password-long', 1002))
        admin.transact(self.path, self.owner, 'reactivate', 1003, target=self.player, reason='reviewed')
        self.assertIsNone(accounts.session(self.path, token, 1004))
        self.assertEqual(accounts.authenticate(self.path, 'player', 'player-password-long', 1004), self.player)
        self.assertEqual(self.sql('SELECT count(*) FROM admin_actions'), [(3,)])

    def test_admin_lockout_and_invalid_actions_roll_back(self):
        for action in ('suspend', 'reset_password'):
            with self.assertRaises(ValueError): admin.transact(self.path, self.owner, action, 1001, target=self.owner, reason='test', password='new-password-long')
        with self.assertRaises(ValueError): admin.transact(self.path, self.owner, 'suspend', 1001, target=self.player, reason='')
        with self.assertRaises(ValueError): admin.transact(self.path, self.owner, 'unknown', 1001, reason='test')
        self.assertEqual(self.sql('SELECT count(*) FROM admin_actions'), [(1,)])

    def test_reset_revokes_sessions_clears_throttle_and_never_audits_secret(self):
        token, _ = accounts.new_session(self.path, self.player, 1000)
        self.sql("INSERT INTO auth_failures VALUES ('player',0,9999)")
        admin.transact(self.path, self.owner, 'reset_password', 1001, target=self.player, reason='requested reset', password='replacement-password')
        self.assertIsNone(accounts.session(self.path, token, 1002))
        self.assertEqual(accounts.authenticate(self.path, 'player', 'replacement-password', 1002), self.player)
        self.assertIsNone(accounts.authenticate(self.path, 'player', 'player-password-long', 1002))
        self.assertNotIn('replacement-password', str(self.sql('SELECT * FROM admin_actions')))

    def test_password_change_requires_current_password_and_revokes_all_sessions(self):
        token, _ = accounts.new_session(self.path, self.owner, 1000)
        with self.assertRaises(ValueError): admin.change_password(self.path, self.owner, 'wrong', 'replacement-password', 1001)
        self.assertIsNotNone(accounts.session(self.path, token, 1001))
        admin.change_password(self.path, self.owner, 'owner-password-long', 'replacement-password', 1002)
        self.assertIsNone(accounts.session(self.path, token, 1003))
        self.assertEqual(accounts.authenticate(self.path, 'owner', 'replacement-password', 1003), self.owner)

    def test_announcement_and_moderation_persist_and_escape_html(self):
        accounts.join(self.path, self.player, 'Player town', 1000)
        self.sql("INSERT INTO board_posts(season_id,author_account_id,body,created_at) VALUES (1,?,'<script>bad</script>',1000)", (self.player,))
        admin.transact(self.path, self.owner, 'hide_post', 1001, target=1, reason='abuse')
        self.assertEqual(self.sql('SELECT moderation_status FROM board_posts'), [('hidden',)])
        admin.transact(self.path, self.owner, 'restore_post', 1002, target=1, reason='reviewed')
        admin.transact(self.path, self.owner, 'announce', 1002, reason='server notice', body='Testing tonight')
        accounts.prepare(self.path)
        self.assertEqual(self.sql("SELECT count(*) FROM notifications WHERE notification_type='admin_announcement'"), [(1,)])
        html = admin.panel(self.path, self.owner, 'token')
        self.assertIn('&lt;script&gt;', html); self.assertNotIn('<script>bad', html)
        self.assertEqual(self.sql('SELECT count(*) FROM admin_actions'), [(4,)])

    def test_backup_restore_preserves_data_and_invalidates_restored_sessions(self):
        token, _ = accounts.new_session(self.path, self.player, 1000)
        saved = backup(self.path, Path(self.tmp.name)/'backup.db')
        with self.assertRaises(FileExistsError): backup(self.path, saved)
        admin.transact(self.path, self.owner, 'suspend', 1001, target=self.player, reason='test')
        recovery = restore(saved, self.path)
        self.assertTrue(recovery.is_file())
        self.assertEqual(self.sql('SELECT is_active FROM accounts WHERE account_id=?', (self.player,)), [(1,)])
        self.assertIsNone(accounts.session(self.path, token, 1002))
        with self.assertRaises(ValueError): restore(self.path, self.path)

    def test_invalid_backup_and_unconfirmed_restore_do_not_replace_save(self):
        invalid = Path(self.tmp.name)/'invalid.db'; invalid.write_text('not sqlite')
        before = self.path.read_bytes()
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--database', str(self.path), 'restore', str(invalid)]), 1)
        self.assertIn('Stop every game server', output.getvalue())
        self.assertEqual(before, self.path.read_bytes())

    def test_suspended_player_does_not_block_other_players_rankings(self):
        from game import expansion
        from game.settlement import account_scope
        accounts.join(self.path, self.owner, 'Owner town', 1000)
        accounts.join(self.path, self.player, 'Player town', 1000)
        with account_scope(self.owner): expansion.transact(self.path, 'enable', 1000)
        admin.transact(self.path, self.owner, 'suspend', 1001, target=self.player, reason='test')
        with account_scope(self.owner): expansion.refresh(self.path, 1060)
        admin.transact(self.path, self.owner, 'reactivate', 1061, target=self.player, reason='reviewed')
        with account_scope(self.owner): expansion.refresh(self.path, 1120)
        self.assertEqual(self.sql('SELECT simulation_processed_at FROM settlements ORDER BY account_id'), [(1120,), (1120,)])

    def test_suspension_recalls_pending_raids_without_duplicate_refunds(self):
        from game import combat
        from game.settlement import account_scope
        from game.simulation import advance_settlement
        sa=accounts.join(self.path,self.owner,'Owner town',1000)
        sb=accounts.join(self.path,self.player,'Player town',1000)
        self.sql('UPDATE settlements SET protection_until=1000')
        cid=self.sql("INSERT INTO citizens(settlement_id,original_settlement_id,name,sex,level,current_hp,morale,status,unemployed_since,created_at) VALUES (?,?,'Raider','unknown',1,100,60,'alive',1000,1000) RETURNING citizen_id",(sa,sa))[0][0]
        self.sql("INSERT INTO citizen_settlement_history(citizen_id,settlement_id,joined_at,arrival_reason) VALUES (?,?,1000,'test_fixture')",(cid,sa))
        self.sql('INSERT INTO citizen_level_history(citizen_id,level,xp_total,reached_at) VALUES (?,1,0,1000)',(cid,))
        with account_scope(self.owner):
            combat.command(self.path,'declare',1000,target_id=sb)
            attack=combat.command(self.path,'launch',4600,target_id=sb,citizen_ids=[cid])
        admin.transact(self.path,self.owner,'suspend',4601,target=self.player,reason='test')
        with account_scope(self.owner):
            advance_settlement(self.path,8200)
            advance_settlement(self.path,8200)
        self.assertEqual(self.sql('SELECT status,allowance_refunded FROM attacks WHERE attack_id=?',(attack,)),[('cancelled',1)])
        self.assertEqual(self.sql('SELECT status FROM citizens WHERE citizen_id=?',(cid,)),[('alive',)])


class AdminHTTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'accounts.db'; accounts.prepare(self.path)
        self.owner = accounts.register(self.path, 'owner', 'owner-password-long', 1000)
        self.player = accounts.register(self.path, 'player', 'player-password-long', 1000)
        admin.grant(self.path, 'owner', 1000)
        self.server = AccountServer(('127.0.0.1', 0), self.path, clock=lambda:1000, allowed_hosts=['192.168.1.25'])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start(); self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def request(self, method='GET', path='/', fields=None, cookie='', headers=None):
        client = http.client.HTTPConnection(*self.server.server_address)
        h = {'Cookie': cookie}; body = urlencode(fields) if fields is not None else None
        if body is not None: h['Content-Type'] = 'application/x-www-form-urlencoded'
        h.update(headers or {}); client.request(method, path, body, h)
        r = client.getresponse(); result = r.status, dict(r.getheaders()), r.read().decode(); client.close(); return result

    def actor(self, aid):
        token, data = accounts.new_session(self.path, aid, 1000)
        return 'settlement_session='+token, data['csrf']

    def test_admin_dashboard_works_without_settlement_and_not_for_players(self):
        cookie, csrf = self.actor(self.owner)
        status, _, html = self.request(path='/admin', cookie=cookie)
        self.assertEqual(status, 200); self.assertIn('Administration', html); self.assertNotIn('password_hash', html)
        player, _ = self.actor(self.player)
        self.assertEqual(self.request(path='/admin', cookie=player)[0], 403)
        self.assertEqual(self.request(path='/admin')[0], 401)
        self.assertEqual(self.request('POST', '/admin', {'token':csrf,'action':'suspend','target':self.player,'reason':'review'}, cookie)[0], 303)

    def test_admin_post_requires_role_token_and_same_origin(self):
        owner, csrf = self.actor(self.owner); player, pcsrf = self.actor(self.player)
        fields = {'token':csrf,'action':'suspend','target':self.player,'reason':'review'}
        self.assertEqual(self.request('POST','/admin',fields,owner,{'Origin':'http://evil.example'})[0],403)
        self.assertEqual(self.request('POST','/admin',dict(fields,token='bad'),owner)[0],403)
        self.assertEqual(self.request('POST','/admin',dict(fields,token=pcsrf),player)[0],403)

    def test_lan_host_and_origin_work_for_registration_and_inherited_game_forms(self):
        port = self.server.server_address[1]; host = f'192.168.1.25:{port}'
        h = {'Host':host,'Origin':'http://'+host}
        status, headers, html = self.request(headers=h)
        self.assertEqual(status,200)
        cookie = headers['Set-Cookie'].split(';')[0]; csrf = re.search('name="token" value="([^"]+)"',html)[1]
        status, headers, _ = self.request('POST','/register',{'token':csrf,'username':'lanplayer','password':'lan-password-long'},cookie,h)
        self.assertEqual(status,303)
        cookie = headers['Set-Cookie'].split(';')[0]
        _, _, html = self.request(cookie=cookie,headers=h); csrf = re.search('name="token" value="([^"]+)"',html)[1]
        self.assertEqual(self.request('POST','/settlement',{'token':csrf,'name':'LAN town'},cookie,h)[0],303)
        # This endpoint belongs to the original handler, so its origin must also accept LAN.
        self.assertEqual(self.request('POST','/administrator',{'token':csrf,'citizen_id':'999999'},cookie,h)[0],400)
        self.assertEqual(self.request(headers={'Host':f'evil.example:{port}'})[0],403)
        self.assertEqual(self.request('POST','/logout',{'token':csrf},cookie,{'Host':host,'Origin':f'http://localhost:{port}'})[0],403)

    def test_password_settings_logs_out_and_rejects_bad_current(self):
        cookie, csrf = self.actor(self.owner)
        self.assertEqual(self.request(path='/account',cookie=cookie)[0],200)
        fields={'token':csrf,'current':'wrong','password':'replacement-password'}
        self.assertEqual(self.request('POST','/account',fields,cookie)[0],400)
        self.assertEqual(self.request('POST','/account',dict(fields,current='owner-password-long'),cookie)[0],303)
        self.assertEqual(self.request(path='/admin',cookie=cookie)[0],401)

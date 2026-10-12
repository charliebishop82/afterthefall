"""Operational admin controls, using isolated saves and deterministic time."""
from contextlib import closing
import json
import sqlite3
from pathlib import Path
import tempfile
import unittest

from database.create_database import connect_database
from game import accounts, admin, lobby, trading, expansion
from game.settlement import account_scope, read_settlement, read_state
from game.simulation import advance_settlement
from tests.fixtures import fixed_map_seed


class OperationalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'game.db'
        lobby.prepare(self.path)
        self.owner = accounts.register(self.path, 'owner', 'owner-password-long', 1000)
        self.player = accounts.register(self.path, 'player', 'player-password-long', 1000)
        admin.grant(self.path, 'owner', 1000)
        lobby.enroll(self.path, self.owner, 'Owner town', 1000)
        lobby.enroll(self.path, self.player, 'Player town', 1000)
        with fixed_map_seed():
            lobby.start(self.path, self.owner, 1000, 'test start')
        self.sid = self.state(self.player)['settlement']['settlement_id']

    def test_fixture_map_keeps_the_construction_plot_clear(self):
        state = self.state(self.player)
        self.assertEqual(state['season']['map_seed'], '1'.zfill(32))
        width, height = state['config']['buildings']['garden']['footprint']
        for ruin in state['derelicts']:
            rw, rh = state['config']['derelicts'][ruin['derelict_type']]['footprint']
            overlaps = (15 < ruin['origin_x']+rw and 15+width > ruin['origin_x']
                        and 15 < ruin['origin_y']+rh and 15+height > ruin['origin_y'])
            self.assertFalse(overlaps, f'Fixture ruin blocks garden plot: {ruin}')

    def sql(self, query, args=()):
        with closing(connect_database(self.path)) as c, c:
            return c.execute(query, args).fetchall()

    def state(self, actor):
        with account_scope(actor): return read_settlement(self.path)

    def action(self, action, now=1000, **kwargs):
        admin.transact(self.path, self.owner, action, now, reason='test correction', **kwargs)

    def pause(self):
        self.action('pause_season', target=1)

    def correction(self, action, value, expected, **kwargs):
        self.action(action, settlement_id=self.sid, value=value, expected=expected, **kwargs)

    def test_pause_freezes_all_players_and_extends_deadlines(self):
        before = self.state(self.player)
        self.pause()
        for actor in (self.owner, self.player):
            with account_scope(actor): advance_settlement(self.path, 90100)
        during = self.state(self.player)
        self.assertEqual(during['resources'], before['resources'])
        self.assertEqual(during['citizens'], before['citizens'])
        self.assertEqual(during['settlement']['simulation_processed_at'], 1000)
        self.action('resume_season', 90100, target=1)
        after = self.state(self.player)
        self.assertEqual(after['season']['ends_at'], before['season']['ends_at']+89100)
        self.assertEqual(after['settlement']['protection_until'], before['settlement']['protection_until']+89100)
        self.assertEqual(after['settlement']['attacks_remaining'], before['settlement']['attacks_remaining'])
        with account_scope(self.player): advance_settlement(self.path, 90100)
        self.assertEqual(self.state(self.player)['resources'], before['resources'])

    def test_suspension_freezes_catchup_and_overlapping_season_pause_once(self):
        self.action('suspend', target=self.player)
        self.action('pause_season', 1001, target=1)
        self.action('resume_season', 1601, target=1)
        self.action('reactivate', 1700, target=self.player)
        state = self.state(self.player)
        self.assertEqual(state['settlement']['simulation_processed_at'], 1700)
        self.assertEqual(state['recovery_clock']['anchor'], 1700)
        self.assertEqual(state['settlement']['status'], 'active')
        with account_scope(self.player): advance_settlement(self.path, 1700)
        self.assertEqual(self.state(self.player)['resources'], state['resources'])

    def test_reactivation_during_season_pause_excludes_overlap(self):
        self.action('suspend', target=self.player)
        self.action('pause_season', 1001, target=1)
        self.action('reactivate', 1100, target=self.player)
        self.action('resume_season', 1601, target=1)
        state = self.state(self.player)
        self.assertEqual(state['recovery_clock']['anchor'], 1601)
        self.assertEqual(state['settlement']['simulation_processed_at'], 1601)

    def test_trade_reservation_expiry_freezes_for_either_participant(self):
        owner_sid = self.state(self.owner)['settlement']['settlement_id']
        with account_scope(self.owner):
            tid = trading.transact(self.path, 'propose', 1000, recipient_id=self.sid,
                                   offered={'scrap': 1}, requested={'water': 1})
        before = self.sql('SELECT expires_at FROM trade_proposals WHERE trade_id=?', (tid,))[0][0]
        self.action('suspend', target=self.player)
        # Ask the expiry service directly; an unrelated day's economy isn't
        # needed to test a shared reservation timer.
        with closing(connect_database(self.path)) as c, c:
            c.row_factory = sqlite3.Row
            with account_scope(self.owner): trading.expire(c, read_state(c), 87500)
        self.assertEqual(self.sql('SELECT status FROM trade_proposals WHERE trade_id=?', (tid,)), [('pending',)])
        self.action('reactivate', 87500, target=self.player)
        self.assertEqual(self.sql('SELECT expires_at FROM trade_proposals WHERE trade_id=?', (tid,)), [(before+86500,)])
        self.assertEqual(self.sql('SELECT quantity FROM resource_reservations WHERE settlement_id=? AND released_at IS NULL', (owner_sid,)), [(1.0,)])

    def test_invalid_pause_permission_status_and_clock_are_atomic(self):
        with self.assertRaises(PermissionError):
            admin.transact(self.path, self.player, 'pause_season', 1000, target=1, reason='test')
        with self.assertRaises(ValueError): self.action('resume_season', target=1)
        self.pause()
        before = self.path.read_bytes()
        for action, time in (('pause_season', 1000), ('resume_season', 999)):
            with self.assertRaises(ValueError): self.action(action, time, target=1)
        self.assertEqual(self.path.read_bytes(), before)

    def test_paused_gameplay_cannot_bypass_freeze_but_communication_works(self):
        self.pause()
        from game import buildings, communication, needs, manufacturing, scavenging
        from game.simulation import apply_action
        state = self.state(self.player)
        cid = state['citizens'][0]['citizen_id']
        with account_scope(self.player):
            for action in (
                lambda: buildings.change_building(self.path, 'release', citizen_id=cid, now=1000),
                lambda: needs.command(self.path, 'rations', 1000),
                lambda: manufacturing.command(self.path, 'cancel', 1000, job_id=1),
                lambda: scavenging.assign(self.path, 'assign', 1, cid, now=1000),
                lambda: apply_action(self.path, 'resume', now=1000),
            ):
                with self.assertRaisesRegex(ValueError, 'frozen'): action()
            communication.transact(self.path, 'post', 1000, body='Waiting for resume')
        self.assertEqual(self.state(self.player)['resources'], state['resources'])

    def test_resource_correction_is_persistent_audited_and_storage_limited(self):
        self.pause()
        previous = self.state(self.player)['resources']['food']
        self.correction('correct_resource', 50, previous, field='food')
        lobby.prepare(self.path)
        self.assertEqual(self.state(self.player)['resources']['food'], 50)
        before, after, reason = self.sql("SELECT before_values,after_values,reason FROM admin_actions WHERE action_type='correct_resource'")[0]
        self.assertEqual(json.loads(before), {'food': previous})
        self.assertEqual(json.loads(after), {'food': 50})
        self.assertEqual(reason, 'test correction')
        for value in (float('nan'), float('inf'), -1, 1e20, 100000):
            with self.assertRaises(ValueError): self.correction('correct_resource', value, 50, field='food')
        self.assertEqual(self.state(self.player)['resources']['food'], 50)

    def test_corrections_require_pause_reason_role_and_matching_old_value(self):
        before = self.state(self.player)['resources']['food']
        with self.assertRaises(ValueError): self.correction('correct_resource', 50, before, field='food')
        self.pause()
        for expected in (before-1, None, float('nan')):
            with self.assertRaises(ValueError): self.correction('correct_resource', 50, expected, field='food')
        with self.assertRaises(ValueError):
            admin.transact(self.path, self.owner, 'correct_resource', 1000, settlement_id=self.sid, field='food', value=50, expected=before, reason='')
        with self.assertRaises(PermissionError):
            admin.transact(self.path, self.player, 'correct_resource', 1000, settlement_id=self.sid, field='food', value=50, expected=before, reason='test')
        self.assertEqual(self.state(self.player)['resources']['food'], before)

    def test_reserved_stock_cannot_be_removed_by_correction(self):
        with account_scope(self.player):
            trading.transact(self.path, 'propose', 1000, recipient_id=self.state(self.owner)['settlement']['settlement_id'], offered={'scrap': 10}, requested={'water': 1})
        self.pause()
        previous = self.state(self.player)['resources']['scrap']
        with self.assertRaises(ValueError): self.correction('correct_resource', 9, previous, field='scrap')
        self.correction('correct_resource', 10, previous, field='scrap')
        self.assertEqual(self.state(self.player)['reserved']['scrap'], 10)

    def test_credits_external_adjustment_preserves_bank_and_records_ledger(self):
        self.pause()
        bank = self.sql('SELECT credits FROM season_bank')
        old = self.state(self.player)['resources']['credits']
        with self.assertRaises(ValueError): self.correction('correct_resource', 1.5, old, field='credits')
        self.correction('correct_resource', old+20, old, field='credits')
        self.assertEqual(self.sql('SELECT credits FROM season_bank'), bank)
        self.assertEqual(self.sql("SELECT amount,balance_after FROM credit_transactions WHERE transaction_type='admin_correction'"), [(20, old+20)])

    def test_citizen_hp_morale_and_building_hp_validate_ownership_and_bounds(self):
        self.pause()
        state = self.state(self.player); citizen = state['citizens'][0]; building = state['buildings'][0]
        self.correction('correct_citizen_hp', 40, citizen['current_hp'], target=citizen['citizen_id'])
        self.correction('correct_citizen_morale', 0, citizen['morale'], target=citizen['citizen_id'])
        self.correction('correct_building_hp', 250, building['current_hp'], target=building['building_id'])
        for action, value, expected, target in (
            ('correct_citizen_hp', 0, 40, citizen['citizen_id']),
            ('correct_citizen_hp', 101, 40, citizen['citizen_id']),
            ('correct_citizen_morale', 101, 0, citizen['citizen_id']),
            ('correct_building_hp', 0, 250, building['building_id']),
            ('correct_building_hp', 249, 250, building['building_id']),
            ('correct_citizen_hp', 40, 100, self.state(self.owner)['citizens'][0]['citizen_id']),
            ('correct_building_hp', 40, 100, self.state(self.owner)['buildings'][0]['building_id']),
        ):
            with self.assertRaises(ValueError): self.correction(action, value, expected, target=target)
        self.assertEqual(self.state(self.player)['citizens'][0]['morale'], 0)
        self.assertEqual(self.state(self.player)['buildings'][0]['current_hp'], 250)

    def test_attack_allowance_is_bounded_whole_and_stale_safe(self):
        self.pause(); old = self.state(self.player)['settlement']['attacks_remaining']
        self.correction('correct_attacks', 0, old)
        for value in (-1, 1.5, 10000):
            with self.assertRaises(ValueError): self.correction('correct_attacks', value, 0)
        self.assertEqual(self.state(self.player)['settlement']['attacks_remaining'], 0)

    def test_debt_correction_changes_no_wallet_balance_and_clears_borrowed_principal(self):
        with account_scope(self.player): lid = expansion.transact(self.path, 'borrow', 1000, amount=50)
        self.pause(); resources = self.state(self.player)['resources']; reserve = self.sql('SELECT credits FROM season_bank')
        self.correction('correct_debt', 20, 50, target=lid)
        from game.banking import principal
        with closing(connect_database(self.path)) as c:
            c.row_factory = sqlite3.Row
            self.assertEqual(principal(c, self.sid), 20)
        self.correction('correct_debt', 0, 20, target=lid)
        self.assertEqual(self.sql('SELECT outstanding_balance,status FROM bank_loans'), [(0, 'repaid')])
        self.assertEqual(self.state(self.player)['resources'], resources)
        self.assertEqual(self.sql('SELECT credits FROM season_bank'), reserve)
        self.assertEqual(self.sql('PRAGMA integrity_check'), [('ok',)])
        self.assertEqual(self.sql('PRAGMA foreign_key_check'), [])

    def test_dashboard_escapes_audit_values_and_exposes_correction_forms(self):
        self.pause(); old = self.state(self.player)['resources']['credits']
        admin.transact(self.path, self.owner, 'correct_resource', 1000, settlement_id=self.sid, field='credits', value=old+1, expected=old, reason='<script>bad</script>')
        html = admin.panel(self.path, self.owner, 'token')
        self.assertIn('correct_resource', html); self.assertIn('resume_season', html)
        self.assertIn('Before:', html); self.assertIn('After:', html)
        self.assertNotIn('<script>bad</script>', html); self.assertIn('&lt;script&gt;', html)

    def test_bank_and_construction_work_are_preserved_without_downtime_interest(self):
        from game import buildings
        with account_scope(self.player):
            lid = expansion.transact(self.path, 'borrow', 1000, amount=50)
            buildings.change_building(self.path, 'build', building_type='garden', x=15, y=15, now=1000)
        before = self.state(self.player)
        self.pause()
        self.action('resume_season', 90100, target=1)
        after = self.state(self.player)
        self.assertEqual(after['jobs'][0]['work_completed'], before['jobs'][0]['work_completed'])
        self.assertEqual(after['jobs'][0]['last_processed_at'], before['jobs'][0]['last_processed_at']+89100)
        self.assertEqual(self.sql('SELECT outstanding_balance,interest_processed_at FROM bank_loans WHERE loan_id=?', (lid,)), [(50, 90100)])
        with account_scope(self.player): advance_settlement(self.path, 90100)
        self.assertEqual(self.sql('SELECT outstanding_balance FROM bank_loans WHERE loan_id=?', (lid,)), [(50,)])

    def test_frozen_shared_attack_and_war_warning_resume_with_remaining_time(self):
        owner_sid = self.state(self.owner)['settlement']['settlement_id']
        self.sql("INSERT INTO attacks(season_id,attacker_settlement_id,defender_settlement_id,launched_at,resolves_at,status,raid_objective,random_seed) VALUES (1,?,?,1000,4600,'in_flight','balanced','test')", (owner_sid, self.sid))
        self.sql("INSERT INTO treaties(season_id,settlement_a_id,settlement_b_id,treaty_type,status,proposer_settlement_id,proposed_at,accepted_at,effective_at) VALUES (1,?,?,'war','active',?,1000,1000,4600)", (owner_sid, self.sid, owner_sid))
        self.pause()
        with account_scope(self.owner): advance_settlement(self.path, 10000)
        self.assertEqual(self.sql('SELECT status,resolves_at FROM attacks'), [('in_flight', 4600)])
        from game import combat
        self.assertEqual(combat.timers(self.path, self.state(self.owner), 10000), {'1': 3600})
        self.assertEqual(combat.war_timers(self.path, self.state(self.owner), 10000), {'1': 3600})
        self.action('resume_season', 10000, target=1)
        self.assertEqual(self.sql('SELECT status,resolves_at FROM attacks'), [('in_flight', 13600)])
        self.assertEqual(self.sql('SELECT effective_at FROM treaties'), [(13600,)])
        self.assertEqual(self.sql('SELECT accepted_at FROM treaties'), [(1000,)])

    def test_correction_rejects_archived_building_projects_and_invalid_debt(self):
        with account_scope(self.player): lid = expansion.transact(self.path, 'borrow', 1000, amount=50)
        self.pause()
        for value in (101, 1.5, -1):
            with self.assertRaises(ValueError): self.correction('correct_debt', value, 50, target=lid)
        with self.assertRaises(ValueError): self.correction('correct_debt', 20, 50, target=999)
        self.sql("UPDATE settlements SET status='archived' WHERE settlement_id=?", (self.sid,))
        with self.assertRaises(ValueError): self.correction('correct_resource', 10, 0, field='food')

    def test_treaty_cooldowns_preserve_history_and_new_cancellations(self):
        from game import diplomacy
        owner_sid = self.state(self.owner)['settlement']['settlement_id']
        tid = self.sql("INSERT INTO treaties(season_id,settlement_a_id,settlement_b_id,treaty_type,status,proposer_settlement_id,proposed_at,accepted_at,effective_at) VALUES (1,?,?,'peace','active',?,1000,1000,1000) RETURNING treaty_id", (owner_sid,self.sid,owner_sid))[0][0]
        self.pause(); self.action('resume_season', 90100, target=1)
        with closing(connect_database(self.path)) as c:
            c.row_factory = sqlite3.Row
            self.assertTrue(diplomacy.war_cooldown(c,owner_sid,self.sid,90100))
            self.assertFalse(diplomacy.war_cooldown(c,owner_sid,self.sid,111700))
        self.assertEqual(self.sql('SELECT accepted_at FROM treaties WHERE treaty_id=?',(tid,)), [(1000,)])
        # Cancellation happened after the first pause. Its new cooldown must not
        # include time that elapsed before it existed.
        self.sql("UPDATE treaties SET status='cancelled',cancelled_at=90100,cooldown_until=111700 WHERE treaty_id=?",(tid,))
        self.action('pause_season', 90100, target=1)
        self.action('resume_season', 90700, target=1)
        with closing(connect_database(self.path)) as c:
            c.row_factory = sqlite3.Row
            self.assertTrue(diplomacy.war_cooldown(c,owner_sid,self.sid,90700))
            self.assertFalse(diplomacy.war_cooldown(c,owner_sid,self.sid,112300))
        self.assertEqual(self.sql('SELECT accepted_at,cancelled_at FROM treaties WHERE treaty_id=?',(tid,)), [(1000,90100)])

    def test_reactivation_never_reopens_an_archived_settlement(self):
        self.action('suspend', target=self.player)
        self.sql("UPDATE settlements SET status='archived' WHERE settlement_id=?", (self.sid,))
        self.sql("UPDATE seasons SET status='finished'")
        self.action('reactivate', 1060, target=self.player)
        self.assertEqual(self.state(self.player)['settlement']['status'], 'archived')
        self.assertEqual(self.sql('SELECT count(*) FROM admin_freezes'), [(0,)])


class OperationalHTTPTests(unittest.TestCase):
    def setUp(self):
        from admin_suite import create_app, COOKIE
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'game.db'; self.now = 1000
        lobby.prepare(self.path)
        self.app = create_app(self.path, clock=lambda:self.now)
        self.owner = accounts.register(self.path, 'owner', 'owner-password-long', 1000)
        self.player = accounts.register(self.path, 'player', 'player-password-long', 1000)
        admin.grant(self.path, 'owner', 1000)
        lobby.enroll(self.path, self.player, 'Player', 1000)
        lobby.start(self.path, self.owner, 1000, 'test start')
        self.client = self.app.test_client()
        token, session = accounts.new_session(self.path, self.owner, 1000)
        self.client.set_cookie(COOKIE, token, domain='127.0.0.1'); self.csrf = session['csrf']
        with account_scope(self.player): self.sid = read_settlement(self.path)['settlement']['settlement_id']

    def post(self, **fields):
        return self.client.post('/admin', data={'token':self.csrf, 'reason':'test', **fields}, base_url='http://127.0.0.1:8768')

    def test_http_pause_correction_stale_rejection_and_resume(self):
        self.assertEqual(self.post(action='pause_season', target=1).status_code, 303)
        page = self.client.get('/controls?section=corrections', base_url='http://127.0.0.1:8768')
        self.assertEqual(page.status_code, 200); self.assertIn('Replacement value', page.text)
        with account_scope(self.player): old = read_settlement(self.path)['resources']['credits']
        fields = dict(action='correct_resource', settlement_id=self.sid, field='credits', expected=old, value=old+5)
        self.assertEqual(self.post(**fields).status_code, 303)
        self.assertEqual(self.post(**fields).status_code, 400)
        self.assertEqual(self.post(**dict(fields, expected=old+5, value='nan')).status_code, 400)
        self.assertEqual(self.post(**dict(fields, expected=old+5, value='bad')).status_code, 400)
        self.now = 1060
        self.assertEqual(self.post(action='resume_season', target=1).status_code, 303)
        with account_scope(self.player): self.assertEqual(read_settlement(self.path)['resources']['credits'], old+5)

    def test_http_role_csrf_and_origin_enforced_for_new_controls(self):
        self.assertEqual(self.post(action='pause_season', target=1, token='bad').status_code, 403)
        response = self.client.post('/admin', data={'token':self.csrf,'reason':'test','action':'pause_season','target':1}, base_url='http://127.0.0.1:8768', headers={'Origin':'https://evil.invalid'})
        self.assertEqual(response.status_code, 403)
        from admin_suite import COOKIE
        token, session = accounts.new_session(self.path, self.player, 1000)
        self.client.set_cookie(COOKIE, token, domain='127.0.0.1'); self.csrf = session['csrf']
        self.assertEqual(self.post(action='pause_season', target=1).status_code, 403)


if __name__ == '__main__': unittest.main()

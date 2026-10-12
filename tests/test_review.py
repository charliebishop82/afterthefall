"""Regression checks for cross-system consistency found during review."""
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
import json

from database.create_database import connect_database
from game import accounts, combat
from game.buildings import change_building
from game.scavenging import assign
from game.settlement import account_scope, read_settlement
from game.simulation import advance_settlement, apply_action


class ConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'review.db'
        accounts.prepare(self.path)
        self.players = []
        for name in ('alpha', 'bravo'):
            aid = self.sql("INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES (?,'!',?,1000) RETURNING account_id", (name, name))[0][0]
            sid = accounts.join(self.path, aid, name, 1000)
            self.players.append((aid, sid))

    def sql(self, query, args=()):
        with closing(connect_database(self.path)) as c, c:
            return c.execute(query, args).fetchall()

    def state(self, aid):
        with account_scope(aid):
            return read_settlement(self.path)

    def test_supply_boundary_does_not_apply_administrator_change(self):
        aid, sid = self.players[0]
        before = self.state(aid)
        self.sql('UPDATE settlement_resources SET food=.01 WHERE settlement_id=?', (sid,))
        with account_scope(aid):
            result = apply_action(self.path, 'assign', citizen_id=before['citizens'][1]['citizen_id'], now=1060)
        self.assertEqual(result['settlement']['status'], 'suspended')
        self.assertEqual(result['citizens'][0]['assignment'], 'administrator')
        self.assertEqual(result['citizens'][1]['assignment'], 'unassigned')

    def test_supply_boundary_does_not_start_building(self):
        aid, sid = self.players[0]
        self.sql('UPDATE settlement_resources SET food=.01 WHERE settlement_id=?', (sid,))
        with account_scope(aid):
            result = change_building(self.path, 'build', building_type='garden', x=0, y=0, now=1060)
        self.assertEqual(result['settlement']['status'], 'suspended')
        self.assertEqual(len(result['buildings']), 1)
        self.assertEqual(result['jobs'], [])

    def test_supply_boundary_does_not_start_scavenging(self):
        aid, sid = self.players[0]
        before = self.state(aid)
        self.sql('UPDATE settlement_resources SET food=.01 WHERE settlement_id=?', (sid,))
        with account_scope(aid):
            result = assign(self.path, 'assign', before['derelicts'][0]['settlement_derelict_id'], before['citizens'][1]['citizen_id'], now=1060)
        self.assertEqual(result['settlement']['status'], 'suspended')
        self.assertEqual(result['jobs'], [])

    def test_shared_end_settles_and_archives_every_player_once(self):
        self.sql('UPDATE seasons SET finalization_at=1050,ends_at=1100')
        with account_scope(self.players[0][0]):
            advance_settlement(self.path, 1100)
        states = [self.state(aid) for aid, sid in self.players]
        for state in states:
            self.assertEqual(state['season']['status'], 'finished')
            self.assertEqual(state['settlement']['status'], 'archived')
            self.assertEqual(state['settlement']['simulation_processed_at'], 1100)
            self.assertGreater(state['citizens'][0]['xp'], 0)
        self.assertEqual(states[0]['resources']['food'], states[1]['resources']['food'])
        for aid, sid in self.players:
            with account_scope(aid):
                advance_settlement(self.path, 1200)
        self.assertEqual(states, [self.state(aid) for aid, sid in self.players])

    def test_shared_end_archives_frozen_player_and_cancels_their_jobs(self):
        aid, sid = self.players[1]
        hall = self.state(aid)['buildings'][0]['building_id']
        self.sql("INSERT INTO settlement_jobs(settlement_id,job_type,target_type,target_building_id,work_required,status,created_at,last_processed_at) VALUES (?,'repair','building',?,3600,'paused',1000,1000)", (sid, hall))
        self.sql("UPDATE settlements SET status='suspended',suspended_at=1000 WHERE settlement_id=?", (sid,))
        self.sql('UPDATE seasons SET finalization_at=1050,ends_at=1100')
        with account_scope(self.players[0][0]):
            advance_settlement(self.path, 1100)
        state = self.state(aid)
        self.assertEqual(state['settlement']['status'], 'archived')
        self.assertEqual(state['settlement']['simulation_processed_at'], 1000)
        self.assertEqual(state['jobs'][0]['status'], 'cancelled')

    def test_battle_at_exact_shared_end_resolves_before_archive(self):
        aid, sid = self.players[0]
        target = self.players[1][1]
        self.sql('UPDATE settlements SET protection_until=1000')
        cid = self.sql("INSERT INTO citizens(settlement_id,original_settlement_id,name,sex,current_hp,morale,status,created_at) VALUES (?,?,'Raider','unknown',100,60,'alive',1000) RETURNING citizen_id", (sid, sid))[0][0]
        with account_scope(aid):
            combat.command(self.path, 'declare', 1000, target_id=target)
            combat.command(self.path, 'launch', 4600, target_id=target, citizen_ids=[cid])
        self.sql('UPDATE seasons SET finalization_at=4700,ends_at=8200')
        with account_scope(aid):
            advance_settlement(self.path, 8200)
        self.assertEqual(self.sql('SELECT status,resolved_at FROM attacks'), [('resolved', 8200)])
        self.assertEqual(self.sql('SELECT count(*) FROM battle_reports'), [(2,)])
        self.assertEqual(self.sql("SELECT count(*) FROM settlements WHERE status='archived'"), [(2,)])

    def test_pending_battle_past_end_returns_raider_and_refunds_once(self):
        aid, sid = self.players[0]
        target = self.players[1][1]
        self.sql('UPDATE settlements SET protection_until=1000')
        cid = self.sql("INSERT INTO citizens(settlement_id,original_settlement_id,name,sex,current_hp,morale,status,created_at) VALUES (?,?,'Raider','unknown',100,60,'alive',1000) RETURNING citizen_id", (sid, sid))[0][0]
        with account_scope(aid):
            combat.command(self.path, 'declare', 1000, target_id=target)
            combat.command(self.path, 'launch', 4600, target_id=target, citizen_ids=[cid])
        self.sql('UPDATE seasons SET finalization_at=4700,ends_at=8100')
        with account_scope(aid):
            advance_settlement(self.path, 8200)
            advance_settlement(self.path, 8300)
        self.assertEqual(self.sql('SELECT status,resolved_at,allowance_refunded FROM attacks'), [('cancelled', 8100, 1)])
        self.assertFalse(next(c for c in self.state(aid)['citizens'] if c['citizen_id'] == cid)['away'])
        self.assertEqual(self.state(aid)['settlement']['attacks_remaining'], 3)

    def test_survivor_arrivals_prevent_duplicate_names_and_preserve_outcomes(self):
        from game.population import discover
        from game.settlement import read_state
        aid, sid = self.players[0]
        with closing(connect_database(self.path)) as c, c, account_scope(aid):
            import sqlite3
            c.row_factory = sqlite3.Row
            for derelict in read_state(c)['derelicts'][:2]:
                loot = json.loads(derelict['random_result'])
                loot['_survivor'].update(name='Iris Ash', roll_pct=0, at_fraction=0)
                derelict['random_result'] = json.dumps(loot)
                c.execute('UPDATE settlement_derelicts SET random_result=? WHERE settlement_derelict_id=?', (derelict['random_result'], derelict['settlement_derelict_id']))
                discover(c, read_state(c), derelict, 1, 1000)
                discover(c, read_state(c), dict(c.execute('SELECT * FROM settlement_derelicts WHERE settlement_derelict_id=?', (derelict['settlement_derelict_id'],)).fetchone()), 1, 1000)
        names = [citizen['name'] for citizen in self.state(aid)['citizens']]
        self.assertEqual(len(names), 8)
        self.assertEqual(len(set(names)), 8)
        self.assertEqual(names.count('Iris Ash'), 1)

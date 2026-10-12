"""Normal late joins and paused reservations on disposable seasons."""
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from database.create_database import connect_database
from game import accounts, admin, lobby
from game.settlement import account_scope, read_settlement, load_config


class MidseasonEnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'playtest.db';lobby.prepare(self.path)
        self.owner=accounts.register(self.path,'owner','owner-password-long',1000)
        admin.grant(self.path,'owner',1000)
        lobby.enroll(self.path,self.owner,'Owner town',1000)
        lobby.start(self.path,self.owner,1000,'Start disposable playtest')
        self.late=accounts.register(self.path,'late','late-password-long',1000)

    def state(self,actor):
        with account_scope(actor):return read_settlement(self.path)

    def test_late_join_has_normal_seed_join_time_protection_and_shared_end(self):
        before=self.state(self.owner)
        lobby.enroll(self.path,self.late,'Late town',1500)
        state=self.state(self.late);config=load_config('prototype_v1')
        self.assertEqual(state['settlement']['created_at'],1500)
        self.assertEqual(state['settlement']['simulation_processed_at'],1500)
        self.assertEqual(state['settlement']['protection_until'],1500+config['beginner_protection_hours']*3600)
        self.assertEqual(len(state['citizens']),config['starting_population'])
        for resource,amount in config['resources'].items():self.assertEqual(state['resources'][resource],amount)
        self.assertEqual(state['season']['ends_at'],before['season']['ends_at'])
        self.assertEqual(state['season']['config_version'],before['season']['config_version'])
        self.assertIsNotNone(state['needs_clock'])
        self.assertEqual(self.state(self.owner)['resources'],before['resources'])

    def test_duplicate_enrollment_and_name_conflicts_do_not_grant_again(self):
        with self.assertRaises(ValueError):lobby.enroll(self.path,self.late,'Owner town',1500)
        lobby.enroll(self.path,self.late,'Late town',1500);before=self.state(self.late)
        with self.assertRaises(ValueError):lobby.enroll(self.path,self.late,'Another name',1501)
        self.assertEqual(self.state(self.late),before)

    def test_paused_reservation_creates_nothing_until_atomic_resume(self):
        season=self.state(self.owner)['season']['season_id']
        admin.transact(self.path,self.owner,'pause_season',1100,target=season,reason='Pause test')
        lobby.enroll(self.path,self.late,'Reserved town',1500)
        self.assertIsNone(self.state(self.late))
        admin.transact(self.path,self.owner,'resume_season',1800,target=season,reason='Resume test')
        state=self.state(self.late)
        self.assertEqual(state['settlement']['created_at'],1800)
        self.assertEqual(state['settlement']['simulation_processed_at'],1800)
        self.assertEqual(state['season']['status'],'active')

    def test_finalization_boundary_rejects_without_membership_or_settlement(self):
        season=self.state(self.owner)['season']
        with self.assertRaises(ValueError):lobby.enroll(self.path,self.late,'Too late',season['finalization_at'])
        self.assertIsNone(self.state(self.late))
        self.assertNotIn(self.late,[m['account_id'] for m in lobby.status(self.path)['members']])
        with self.assertRaises(ValueError):accounts.join(self.path,self.late,'Direct too late',season['finalization_at'])

    def test_join_failure_rolls_back_reservation_and_partial_seed(self):
        with patch('game.lobby.join_member',side_effect=RuntimeError('Injected failure')):
            with self.assertRaises(RuntimeError):lobby.enroll(self.path,self.late,'Failed join',1500)
        self.assertIsNone(self.state(self.late))
        self.assertNotIn(self.late,[m['account_id'] for m in lobby.status(self.path)['members']])

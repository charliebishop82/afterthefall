"""Bot controls and decisions on disposable saves; no running game required."""
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from database.create_database import connect_database
from game import accounts,admin,bots,lobby
from game.bot_policy import choose
from game.settlement import account_scope,read_settlement,load_config
from run_bots import game_origin,step


class EconomyBotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'test.db';lobby.prepare(self.path);bots.prepare(self.path)
        self.owner=accounts.register(self.path,'owner','owner-password-long',1000)
        admin.grant(self.path,'owner',1000)
        lobby.enroll(self.path,self.owner,'Owner town',1000);lobby.start(self.path,self.owner,1000,'Start test')

    def state(self,aid):
        with account_scope(aid):return read_settlement(self.path)

    def test_create_uses_normal_seed_and_starts_controller_paused(self):
        aid=bots.create(self.path,self.owner,'bot_one','Bot town',1000)
        state=self.state(aid);config=load_config('prototype_v1')
        for r,v in config['resources'].items():self.assertEqual(state['resources'][r],v)
        self.assertEqual(len(state['citizens']),config['starting_population'])
        with closing(connect_database(self.path)) as c:
            self.assertEqual(c.execute('SELECT is_admin FROM accounts WHERE account_id=?',(aid,)).fetchone()[0],0)
            self.assertEqual(c.execute('SELECT state FROM bot_controllers WHERE account_id=?',(aid,)).fetchone()[0],'paused')
        self.assertIsNone(bots.claim(self.path,1000))

    def test_start_pause_and_claim_are_explicit(self):
        aid=bots.create(self.path,self.owner,'bot_one','Bot town',1000)
        bots.control(self.path,self.owner,aid,'start',1000)
        self.assertEqual(bots.claim(self.path,1000)['account_id'],aid)
        self.assertIsNone(bots.claim(self.path,1000))
        bots.record(self.path,aid,1000,dict(route=None,reason='Wait',form={}))
        bots.control(self.path,self.owner,aid,'pause',1001)
        self.assertIsNone(bots.claim(self.path,1200))

    def test_duplicate_settlement_rolls_back_new_account(self):
        with self.assertRaises(ValueError):bots.create(self.path,self.owner,'bot_one','Owner town',1000)
        with closing(connect_database(self.path)) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM accounts WHERE username='bot_one'").fetchone()[0],0)

    def test_non_admin_cannot_create_or_start_bots(self):
        ordinary=accounts.register(self.path,'ordinary','ordinary-password-long',1000)
        with self.assertRaises(PermissionError):bots.create(self.path,ordinary,'bot_one','Bot town',1000)

    def test_policy_restores_admin_and_assigns_project_worker(self):
        citizen=dict(citizen_id=7,assignment='unassigned',current_hp=10,job_id=None)
        state=dict(season={'status':'active'},settlement={'status':'active'},citizens=[citizen])
        decision=choose(state,{},1)
        self.assertEqual(decision['route'],'/administrator')
        state['citizens'].append(dict(citizen_id=8,assignment='administrator',current_hp=10,job_id=None))
        state['jobs']=[dict(job_id=1,job_type='upgrade',status='paused',target_building_id=3)]
        state['buildings']=[dict(building_id=3,building_type='town_hall')]
        decision=choose(state,{},1)
        self.assertEqual(decision['form']['action'],'builder')
        self.assertEqual(decision['form']['citizen_id'],7)

    def test_policy_paused_season_waits_without_needing_private_opponents(self):
        self.assertIsNone(choose(dict(season={'status':'paused'},settlement={'status':'active'}),{},1)['route'])

    def test_runner_records_refresh_rejection_and_removes_session(self):
        aid=bots.create(self.path,self.owner,'bot_one','Bot town',1000)
        with patch('run_bots.time.time',return_value=1000),patch('run_bots.request',return_value=(403,b'rejected','request-test')):
            self.assertEqual(step(self.path,'http://127.0.0.1:8767',dict(account_id=aid,seed=1,steps=0)),'Refresh rejected')
        with closing(connect_database(self.path)) as c:
            self.assertEqual(c.execute('SELECT status,request_id FROM bot_decisions WHERE account_id=?',(aid,)).fetchone(),(403,'request-test'))
            self.assertEqual(c.execute('SELECT count(*) FROM auth_sessions WHERE account_id=?',(aid,)).fetchone()[0],0)

    def test_runner_only_accepts_local_origins(self):
        self.assertEqual(game_origin('http://127.0.0.1:8767/'),'http://127.0.0.1:8767')
        for value in ('http://example.com','http://localhost/private','http://name:password@localhost'):
            with self.assertRaises(ValueError):game_origin(value)

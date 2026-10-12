"""Bot history retention, profiles and safe own-state observation payloads."""
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from database.create_database import connect_database
from game import accounts,admin,bots,lobby
from run_bots import observations


class BotAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'test.db';lobby.prepare(self.path);bots.prepare(self.path)
        self.owner=accounts.register(self.path,'owner','owner-password-long',1000)
        admin.grant(self.path,'owner',1000)

    def test_personality_is_persisted_and_invalid_profile_creates_nothing(self):
        aid=bots.create(self.path,self.owner,'builder_bot','Builder town',1000,personality='builder')
        with closing(connect_database(self.path)) as c:
            self.assertEqual(c.execute('SELECT personality FROM bot_controllers WHERE account_id=?',(aid,)).fetchone()[0],'builder')
        with self.assertRaises(ValueError):bots.create(self.path,self.owner,'bad_bot','Bad town',1000,personality='raider')
        with closing(connect_database(self.path)) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM accounts WHERE username='bad_bot'").fetchone()[0],0)

    def test_history_is_not_silently_pruned_at_old_limit(self):
        aid=bots.create(self.path,self.owner,'audit_bot','Audit town',1000)
        with closing(connect_database(self.path)) as c,c:
            c.executemany('INSERT INTO bot_decisions(account_id,occurred_at,reason,parameters) VALUES (?,1000,\'old\',\'{}\')',[(aid,)]*1001)
        bots.record(self.path,aid,1001,dict(route=None,reason='Wait',form={}))
        with closing(connect_database(self.path)) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM bot_decisions WHERE account_id=?',(aid,)).fetchone()[0],1002)

    def test_trace_preserves_phase_payload_and_prepare_is_idempotent(self):
        aid=bots.create(self.path,self.owner,'audit_bot','Audit town',1000)
        bots.trace(self.path,aid,'action_rejected',dict(attempt='one',status=400,request_id='request-one'))
        bots.prepare(self.path)
        with closing(connect_database(self.path)) as c:
            row=c.execute('SELECT phase,payload,timestamp_utc FROM bot_traces WHERE account_id=?',(aid,)).fetchone()
            self.assertEqual(row[0],'action_rejected')
            self.assertEqual(json.loads(row[1])['request_id'],'request-one')
            self.assertTrue(row[2].endswith('+00:00'))

    def test_observations_exclude_private_rolls_and_credentials(self):
        state=dict(settlement={'simulation_processed_at':1000,'status':'active'},season={'status':'active'},
                   resources={'food':10},citizens=[],buildings=[],jobs=[],
                   derelicts=[dict(settlement_derelict_id=1,derelict_type='small',status='scavenging',
                                    recovered_loot='{}',random_result='private-roll',random_nonce='private-nonce')],
                   cookie='secret-cookie',csrf='secret-token')
        with patch('game.economy.storage',return_value={'food':100}):data=observations(state)
        serialized=json.dumps(data)
        for secret in ('private-roll','private-nonce','secret-cookie','secret-token'):
            self.assertNotIn(secret,serialized)
        self.assertEqual(data['resources']['food'],10)

    def test_affordable_production_upgrade_addresses_a_supply_deficit(self):
        from game.bot_policy import choose
        state=dict(season={'status':'active','finalization_at':2000},
                   settlement={'status':'active','simulation_processed_at':1000},
                   resources=dict(food=20,water=50,scrap=100,metal=100,electronics=100),
                   citizens=[dict(citizen_id=1,assignment='administrator',current_hp=100,building_id=1,job_id=None),
                             dict(citizen_id=2,assignment='unassigned',current_hp=100,building_id=None,job_id=None),
                             dict(citizen_id=3,assignment='production',current_hp=100,building_id=2,job_id=None)],
                   buildings=[dict(building_id=1,building_type='town_hall',status='active',level=1),
                              dict(building_id=2,building_type='greenhouse',status='active',level=1)],
                   jobs=[],derelicts=[],config={'buildings':{'town_hall':{'max_level':3},'greenhouse':{'max_level':2}}})
        current=dict(workers=1,food=10,water=0,scrap=10,metal=0,electronics=0,
                     material_storage=0,housing=0,food_storage=0,water_storage=0)
        target=dict(current,food=20)
        with patch('game.bot_policy.spec',side_effect=lambda state,b,level=None:target if level==2 else current), \
             patch('game.economy.storage',return_value=dict(food=100,water=100,material=300)), \
             patch('game.population.housing',return_value={'homeless':0}):
            decision=choose(state,{'food':{'net':-5},'water':{'net':0}},1,'balanced')
        self.assertEqual(decision['form'],dict(action='upgrade',building_id=2,expected_level=1))
        self.assertEqual(decision['policy_version'],'expeditions-v5')

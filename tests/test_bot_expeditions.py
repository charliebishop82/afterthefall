"""Personality, reserves, staffing, early recall and seeded variation."""
import copy
import json
import unittest
from unittest.mock import patch
from game.bot_expeditions import choose_expedition

def action(route,reason,**form):return dict(route=route,reason=reason,form=form)

class BotExpeditionTests(unittest.TestCase):
    def setUp(self):
        self.free=[dict(citizen_id=i,level=i,current_hp=100,assignment='unassigned',job_id=None) for i in range(1,5)]
        self.state=dict(season=dict(status='active',config_version='prototype_v1',finalization_at=50000,ends_at=60000),
            settlement=dict(status='active',simulation_processed_at=1000),
            citizens=self.free+[dict(citizen_id=5,assignment='administrator',job_id=None),dict(citizen_id=6,assignment='production',job_id=None)],
            resources=dict(food=120,water=120,scrap=20,metal=10,electronics=0),reserved={},
            expeditions=[],jobs=[],config=dict(simulation=dict(food_per_citizen_per_hour=1,water_per_citizen_per_hour=1)))
        self.rates={r:dict(net=0,consumption=6) for r in ('food','water')}
        p=patch('game.economy.storage',return_value=dict(food=150,water=150,material=250));p.start();self.addCleanup(p.stop)
    def choose(self,profile='scavenger',seed=1,**kwargs):
        return choose_expedition(self.state,self.rates,seed,profile,action,self.free,**kwargs)
    def test_scavenger_sends_two_high_level_idle_citizens_and_preserves_workers(self):
        before=copy.deepcopy(self.state);chosen=self.choose()
        self.assertEqual(chosen['form']['citizen_id'],[4,3])
        self.assertEqual(chosen['form']['food'],12)
        self.assertNotIn(5,chosen['form']['citizen_id']);self.assertNotIn(6,chosen['form']['citizen_id'])
        self.assertEqual(self.state,before)
    def test_defensive_and_aggressive_keep_six_home(self):
        self.assertIsNone(self.choose('defensive',seed=31))
        self.assertIsNone(self.choose('aggressive'))
        self.state['citizens'].append(dict(citizen_id=7,assignment='production',job_id=None))
        self.assertIsNotNone(self.choose('defensive',seed=31))
    def test_seeded_variation_and_balanced_smaller_party(self):
        self.assertIsNone(self.choose(seed=0))
        first=self.choose('balanced');self.assertEqual(first,self.choose('balanced'))
        self.assertEqual(len(first['form']['citizen_id']),1)
    def test_food_buffer_deficit_and_project_block_launch(self):
        self.state['resources']['food']=36
        self.assertIsNone(self.choose())
        self.state['resources']['food']=120;self.rates['food']['net']=-1
        self.assertIsNone(self.choose())
        self.rates['food']['net']=0
        self.state['jobs']=[dict(job_type='construction',status='active',job_id=9)]
        self.assertIsNone(self.choose())
    def test_active_trip_prevents_second_and_returning_trip_is_not_recalled(self):
        self.state['expeditions']=[dict(status='returning')]
        self.assertIsNone(self.choose())
    def test_supply_pressure_recalls_existing_trip(self):
        self.state['expeditions']=[dict(status='exploring',expedition_id=2,started_at=0,yields=json.dumps(dict(scrap=2)))]
        self.state['resources']['food']=0;self.rates['food']['net']=-6
        chosen=self.choose(recall_only=True)
        self.assertEqual(chosen['form'],dict(action='recall',expedition_id=2))
    def test_full_storage_and_pause_prevent_launches(self):
        self.state['resources']['scrap']=250
        self.assertIsNone(self.choose())
        self.state['resources']['scrap']=20;self.state['season']['status']='paused'
        self.assertIsNone(self.choose())

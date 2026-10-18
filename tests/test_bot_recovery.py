"""Bot recovery decisions without creating a world or submitting actions."""
import copy
import unittest
from unittest.mock import patch
from game.bot_market import make_room
from game.bot_recovery import choose_supply,release_unsafe,idle_reason


def action(route,reason,**form):return dict(route=route,reason=reason,form=form)

class RecoveryTests(unittest.TestCase):
    def test_full_storage_can_sell_zero_income_scrap_without_spending_project_reserve(self):
        state=dict(resources=dict(scrap=190,metal=37,electronics=23),reserved={},jobs=[])
        market=dict(resources={r:dict(sell_price=2) for r in state['resources']})
        before=copy.deepcopy(state)
        result=make_room(state,{},market,dict(scrap=80,metal=55,electronics=0),action)
        self.assertEqual(result['form'],dict(action='sell',resource='scrap',quantity=25))
        self.assertEqual(state,before)
        state['reserved']['scrap']=110
        state['reserved']['electronics']=13
        self.assertIsNone(make_room(state,{},market,dict(scrap=80,metal=55,electronics=0),action))

    def test_storage_relief_preserves_pending_manufacturing_inputs(self):
        state=dict(resources=dict(scrap=250,metal=0,electronics=0),jobs=[dict(job_type='manufacturing',status='queued')])
        self.assertIsNone(make_room(state,{},dict(resources={}),{},action))

    def test_water_deficit_can_build_a_second_owned_collector(self):
        level=dict(water=3,workers=0,scrap=25,metal=0,electronics=0)
        state=dict(jobs=[],season=dict(status='active',finalization_at=10000),settlement=dict(simulation_processed_at=1000),
                   buildings=[dict(building_type='rain_collector',status='active')],citizens=[],
                   resources=dict(scrap=100,metal=0,electronics=0),reserved={})
        with patch('game.bot_recovery.rules',return_value=dict(buildings=dict(rain_collector=dict(levels=[level],unlock=1)))),patch('game.bot_recovery.spec',return_value=level),patch('game.bot_military.build_plan',return_value=dict(building_type='rain_collector',x=1,y=2,rotation=0)):
            result=choose_supply(state,dict(water=dict(net=-1)),[dict(citizen_id=7)],None,action)
        self.assertEqual(result['route'],'/buildings')
        self.assertEqual(result['form']['action'],'build')
        self.assertIn('water deficit',result['reason'])

    def test_unsafe_paused_scavenging_releases_worker_using_normal_action(self):
        state=dict(jobs=[dict(job_id=4,job_type='scavenging',status='paused',target_derelict_id=9)],
                   derelicts=[dict(settlement_derelict_id=9)],citizens=[dict(citizen_id=8,assignment='scavenging',job_id=4,away=False)])
        with patch('game.scavenging.safe_coverage',return_value=0),patch('game.bot_recovery.rules',return_value=dict(construction=dict(coverage_fraction=.5))):
            result=release_unsafe(state,action)
        self.assertEqual(result['form'],dict(action='release',derelict_id=9,citizen_id=8))

    def test_wait_explains_storage_coverage_and_water_constraints(self):
        state=dict(resources=dict(scrap=250,metal=0,electronics=0),derelicts=[])
        with patch('game.economy.storage',return_value=dict(material=250)):
            reason=idle_reason(state,[],dict(water=dict(net=-1)))
        self.assertIn('material storage full',reason)
        self.assertIn('water production below consumption',reason)
        self.assertIn('safe oxygen coverage',reason)

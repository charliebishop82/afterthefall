"""Stable bot planning without live servers, clocks, or world creation."""
import copy
import unittest
from unittest.mock import patch
from game.bot_strategy import worker_reserve,military_growth_allowed,opening_upgrade,expansion_plan
from game.bot_policy import choose_scavenging
from game.economy import coverage_fraction

def action(route,reason,**form):return dict(route=route,reason=reason,form=form)

class StrategyTests(unittest.TestCase):
    def test_worker_reserve_preserves_an_operator_and_scavenger_expedition_space(self):
        self.assertEqual(worker_reserve('balanced'),1);self.assertEqual(worker_reserve('scavenger'),2)
        result=choose_scavenging({},[{'citizen_id':1}],1,action,personality='balanced')
        self.assertIsNone(result['route']);self.assertIn('reserve idle',result['reason'])
        self.assertIsNone(choose_scavenging({},[{},{}],1,action,personality='scavenger')['route'])

    def test_optional_military_growth_waits_for_the_opening_upgrade(self):
        state={'buildings':[{'level':1,'status':'active'}]}
        self.assertFalse(military_growth_allowed(state));state['buildings'][0]['status']='upgrading';self.assertTrue(military_growth_allowed(state))
        state['buildings'][0].update(level=2,status='active');self.assertTrue(military_growth_allowed(state))

    def test_affordable_opening_goal_is_an_ordinary_upgrade_action(self):
        state={'buildings':[{'building_id':1,'level':1,'status':'active'}],'jobs':[],'season':{'status':'active','finalization_at':10000},'settlement':{'simulation_processed_at':1000},'resources':{'scrap':150,'metal':50,'electronics':5}}
        before=copy.deepcopy(state)
        with patch('game.bot_strategy.spec',return_value={'scrap':150,'metal':50,'electronics':5}),patch('game.bot_strategy.town_hall_preparation',return_value=None):result=opening_upgrade(state,[{}],None,1,action)
        self.assertEqual(result['form'],{'action':'upgrade','building_id':1,'expected_level':1});self.assertEqual(state,before)

    def test_oxygen_extension_is_reachable_and_unlocks_a_specific_ruin(self):
        config={'map_width':8,'map_height':8,'construction':{'coverage_fraction':.5},'buildings':{
          'town_hall':{'footprint':[2,2],'levels':[{'radius':2}]},
          'oxygen_garden':{'footprint':[1,1],'unlock':1,'workers_min':0,'oxygen_required':False,'electricity_required':False,'levels':[{'radius':2,'oxygen_output':4,'scrap':40,'metal':0,'electronics':0}]}},'derelicts':{'ruin':{'footprint':[1,1]}}}
        hall={'building_id':1,'building_type':'town_hall','origin_x':0,'origin_y':0,'level':1,'status':'active'}
        site={'derelict_type':'ruin','origin_x':5,'origin_y':1,'status':'untouched'}
        state={'season':{'config_version':'prototype_v13'},'config':config,'buildings':[hall],'derelicts':[site]}
        with patch('game.economy.utilities',return_value={'zones':{'oxygen':[hall]}}):plan=expansion_plan(state)
        self.assertIsNotNone(plan)
        candidate={'building_type':plan['building_type'],'origin_x':plan['x'],'origin_y':plan['y'],'rotation':plan['rotation'],'level':1}
        self.assertGreaterEqual(coverage_fraction(state,plan['x'],plan['y'],1,1,[hall]),.5)
        self.assertLess(coverage_fraction(state,5,1,1,1,[hall]),.5)
        self.assertGreaterEqual(coverage_fraction(state,5,1,1,1,[hall,candidate]),.5)

    def test_no_oxygen_expansion_when_a_safe_uncleared_ruin_remains(self):
        state={'config':{'buildings':{},'construction':{'coverage_fraction':.5},'derelicts':{'r':{'footprint':[1,1]}}},'buildings':[{}],'derelicts':[{'status':'untouched','derelict_type':'r','origin_x':1,'origin_y':1}]}
        with patch('game.economy.utilities',return_value={'zones':{'oxygen':[]}}),patch('game.economy.coverage_fraction',return_value=1):self.assertIsNone(expansion_plan(state))

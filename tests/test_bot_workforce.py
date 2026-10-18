"""Worker and upgrade planning without creating a world or running simulation."""
import copy
import unittest
from unittest.mock import patch
from game.bot_strategy import worker_reserve,staff_active_project,supply_buffer,town_hall_preparation

def action(route,reason,**form):return {'route':route,'reason':reason,'form':form}

class WorkforceTests(unittest.TestCase):
    def test_reserve_adapts_to_work_supply_and_expedition_context(self):
        self.assertEqual(worker_reserve('scavenger'),2)
        state={'jobs':[{'job_type':'upgrade','status':'active'}]}
        self.assertEqual(worker_reserve('scavenger',state,{}),0)
        self.assertEqual(worker_reserve('balanced',{'jobs':[]},{'water':{'net':-1}}),0)
        self.assertEqual(worker_reserve('scavenger',{'expeditions':[{'status':'exploring'}]},{}),1)

    def test_additional_builder_requires_an_actual_speed_gain_and_preserves_state(self):
        state={'buildings':[{'building_id':1,'building_type':'town_hall'}],
               'citizens':[{'citizen_id':1,'assignment':'construction','job_id':7},{'citizen_id':2,'assignment':'unassigned','job_id':None}],
               'jobs':[{'job_id':7,'job_type':'upgrade','status':'active','target_building_id':1}]}
        before=copy.deepcopy(state)
        with patch('game.buildings.productivity',return_value=1),patch('game.buildings.job_speed',side_effect=[1,1.6]):
            result=staff_active_project(state,[state['citizens'][1]],{},action)
        self.assertEqual(result['form'],{'action':'builder','building_id':1,'citizen_id':2});self.assertEqual(state,before)
        with patch('game.buildings.productivity',return_value=.1),patch('game.buildings.job_speed',side_effect=[1,.9]):
            self.assertIsNone(staff_active_project(state,[state['citizens'][1]],{},action))

    def test_project_staffing_preserves_an_emergency_supply_operator(self):
        state={'resources':{'food':1,'water':50}}
        with patch('game.bot_strategy.available',side_effect=lambda s,r:s['resources'][r]):
            self.assertIsNone(staff_active_project(state,[{}],{'food':{'net':-1,'consumption':6}},action))

    def test_buffer_covers_upgrade_deficit_and_two_hours_of_consumption(self):
        self.assertEqual(supply_buffer(-2,6,3),18)
        self.assertEqual(supply_buffer(3,6,3),12)

    def test_upgrade_replenishes_supplies_before_starting(self):
        hall={'building_id':1,'level':1,'status':'active'}
        state={'buildings':[hall],'resources':{'food':1,'water':100}}
        rates={'food':{'net':-2,'consumption':6},'water':{'net':0,'consumption':6}}
        decision=action('/market','buffer',action='reserve_buy',resource='food',quantity=15)
        with patch('game.simulation.resource_rates',return_value=rates),patch('game.buildings.productivity',return_value=1),patch('game.bot_strategy.spec',return_value={'minutes':120}),patch('game.bot_strategy.available',side_effect=lambda s,r:s['resources'][r]),patch('game.bot_market.purchase',return_value=decision) as buy:
            result=town_hall_preparation(state,[{}],{},1,action)
        self.assertEqual(result,decision);self.assertEqual(buy.call_args.args[2:4],('food',15))
        self.assertEqual(hall['status'],'active')

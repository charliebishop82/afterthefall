import unittest
from unittest.mock import patch
from urllib.parse import urlencode,parse_qs
from game.bot_military import combat_decision


class BotCombatTests(unittest.TestCase):
    def state(self,population=8):
        return dict(season={'status':'active','finalization_at':2000},
                    settlement={'status':'active','simulation_processed_at':1000,'attacks_remaining':3},
                    citizens=[dict(citizen_id=i+1,assignment='administrator' if i==0 else 'unassigned',
                                   current_hp=100,integrated=True) for i in range(population)],expansion=True)

    def target(self,**changes):
        data=dict(settlement_id=9,blocked=False,raid_in_flight=False,protection_until=0,war_effective_at=1000)
        data.update(changes);return data

    def decide(self,state,targets,profile='aggressive'):
        def action(route,reason,**form):return dict(route=route,reason=reason,form=form)
        with patch('game.combat.rule',side_effect=lambda key:{'raid_home_population_min':6,'citizen_low_hp_raid_threshold':25}[key]), \
             patch('game.combat.maximum_hp',return_value=100),patch('game.drones.ready',return_value=[]), \
             patch('game.structural.ammunition',return_value=[]),patch('game.structural.enabled',return_value=True):
            return combat_decision(state,targets,profile,1,action)

    def test_launch_preserves_six_home_and_does_not_send_administrator(self):
        result=self.decide(self.state(),[self.target()])
        self.assertEqual(result['form']['action'],'launch')
        self.assertEqual(len(result['form']['citizen_id']),2)
        self.assertNotIn(1,result['form']['citizen_id'])

    def test_warning_is_required_before_launch(self):
        self.assertEqual(self.decide(self.state(),[self.target(war_effective_at=None)])['form']['action'],'declare')
        self.assertIsNone(self.decide(self.state(),[self.target(war_effective_at=1100)]))

    def test_protection_treaties_and_existing_raid_block_target_choice(self):
        for changes in ({'protection_until':1100},{'blocked':True},{'raid_in_flight':True}):
            self.assertIsNone(self.decide(self.state(),[self.target(**changes)]))

    def test_defensive_profile_allowance_and_home_population_limits(self):
        self.assertIsNone(self.decide(self.state(),[self.target()],'defensive'))
        self.assertIsNone(self.decide(self.state(6),[self.target()]))
        state=self.state();state['settlement']['attacks_remaining']=0
        self.assertIsNone(self.decide(state,[self.target()]))

    def test_injured_or_unintegrated_citizens_are_not_selected(self):
        state=self.state();state['citizens'][1]['current_hp']=10;state['citizens'][2]['integrated']=False
        selected=self.decide(state,[self.target()])['form']['citizen_id']
        self.assertNotIn(2,selected);self.assertNotIn(3,selected)

    def test_multi_unit_form_encoding_preserves_each_selection(self):
        data=parse_qs(urlencode(dict(citizen_id=[2,3],drone_id=[8,9]),doseq=True))
        self.assertEqual(data['citizen_id'],['2','3'])
        self.assertEqual(data['drone_id'],['8','9'])

    def test_manufacturing_queues_one_unit_and_requires_affordability_and_storage(self):
        from game.bot_military import choose_military
        state=dict(season={'status':'active','finalization_at':2000},
                   settlement={'simulation_processed_at':1000},jobs=[],
                   buildings=[dict(building_id=1,building_type='drone_factory',status='active')],
                   citizens=[dict(building_id=1,assignment='production')],
                   resources=dict(metal=20,electronics=10),units=[],inventory=[],
                   config={'units':{'offensive_drone':dict(factory='drone_factory',storage='offensive_hangar',metal=10,electronics=5)}})
        def action(route,reason,**form):return dict(route=route,reason=reason,form=form)
        with patch('game.bot_military.combat_decision',return_value=None), \
             patch('game.bot_military.spec',return_value={'workers':1}), \
             patch('game.manufacturing.home_for',return_value={'building_id':2}):
            decision=choose_military(state,[],'aggressive',1,action,[])
            self.assertEqual(decision['form']['quantity'],1)
            self.assertEqual(decision['form']['repeat'],'0')
            state['resources']['metal']=0
            self.assertIsNone(choose_military(state,[],'aggressive',1,action,[]))
        state['resources']['metal']=20
        with patch('game.bot_military.combat_decision',return_value=None), \
             patch('game.bot_military.spec',return_value={'workers':1}), \
             patch('game.manufacturing.home_for',return_value=None):
            self.assertIsNone(choose_military(state,[],'aggressive',1,action,[]))

    def test_factory_staffing_precedes_manufacturing_when_worker_available(self):
        from game.bot_military import choose_military
        state=dict(season={'status':'active','finalization_at':2000},
                   settlement={'simulation_processed_at':1000},jobs=[],
                   buildings=[dict(building_id=1,building_type='drone_factory',status='active')],
                   citizens=[],config={'units':{}})
        def action(route,reason,**form):return dict(route=route,reason=reason,form=form)
        with patch('game.bot_military.combat_decision',return_value=None), \
             patch('game.bot_military.spec',return_value={'workers':1}),patch('game.bot_military.coverage',return_value=1), \
             patch('game.bot_military.rules',return_value={'construction':{'coverage_fraction':.5}}):
            decision=choose_military(state,[],'aggressive',1,action,[{'citizen_id':8}])
        self.assertEqual(decision['form'],dict(action='worker',building_id=1,citizen_id=8))


    def test_ready_war_is_launched_before_declaring_against_another_target(self):
        ready=self.target(settlement_id=12,war_effective_at=900)
        undeclared=self.target(settlement_id=13,war_effective_at=None)
        result=self.decide(self.state(),[undeclared,ready])
        self.assertEqual(result['form']['action'],'launch')
        self.assertEqual(result['form']['target_id'],12)

    def test_pending_warning_prevents_a_chain_of_new_war_declarations(self):
        self.assertIsNone(self.decide(self.state(),[self.target(war_effective_at=1100),self.target(settlement_id=10,war_effective_at=None)]))

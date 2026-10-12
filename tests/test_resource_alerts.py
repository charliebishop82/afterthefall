"""Forecast alerts do not change state or invent resource storage rules."""
import copy
import unittest
from game.resource_alerts import alerts, panel


class ResourceAlertTests(unittest.TestCase):
    def state(self):
        return dict(season={'status':'active'},settlement={'status':'active'},
                    resources=dict(food=50,water=50,scrap=20,metal=20,electronics=20,credits=100000))

    def rates(self):
        return {r:dict(net=0,capacity=100,hours_to_empty=None)
                for r in ('food','water','scrap','metal','electronics')}

    def test_full_food_surplus_and_empty_water_are_prioritized(self):
        state=self.state();rates=self.rates();state['resources'].update(food=100,water=0)
        rates['food']['net']=5
        rows=alerts(state,rates)
        self.assertEqual([r['key'] for r in rows],['water-empty','food-overflow'])
        self.assertIn('5.0/hour',rows[1]['message'])

    def test_material_capacity_is_shared_not_three_separate_limits(self):
        state=self.state();state['resources'].update(scrap=60,metal=30,electronics=10)
        rows=alerts(state,self.rates())
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['key'],'materials-full')
        self.assertEqual(rows[0]['resources'],['scrap','metal','electronics'])

    def test_filling_and_shortage_estimates_use_current_net_rates(self):
        state=self.state();rates=self.rates();state['resources']['food']=95
        rates['food']['net']=10
        rates['metal'].update(net=-5,hours_to_empty=2)
        keys={r['key'] for r in alerts(state,rates)}
        self.assertEqual(keys,{'food-filling','metal-low'})
        rates['food']['net']=0;rates['metal']['hours_to_empty']=2.1
        self.assertEqual(alerts(state,rates),[])

    def test_paused_forecasts_do_not_claim_current_discarding_or_mutate_save(self):
        state=self.state();state['season']['status']='paused';state['resources']['food']=100
        before=copy.deepcopy(state);rates=self.rates();rates['food']['net']=10
        rows=alerts(state,rates)
        self.assertTrue(rows[0]['message'].startswith('When play resumes:'))
        self.assertEqual(state,before)
        self.assertIn('Needs attention',panel(rows))

    def test_credits_and_stable_stock_have_no_false_storage_warning(self):
        self.assertEqual(alerts(self.state(),self.rates()),[])
        self.assertIn('No resource storage',panel([]))
        rates=self.rates();rates['food'].update(capacity=0,net=1)
        self.assertIn('food-overflow',[r['key'] for r in alerts(self.state(),rates)])

"""Full markers use real shared caps, regardless of net production."""
import copy
import unittest
from game.storage_display import storage_status,badge

class StorageDisplayTests(unittest.TestCase):
    def state(self):
        return dict(resources=dict(food=100,water=20,scrap=60,metal=30,electronics=10,credits=999999),
                    config=dict(town_hall=dict(material_storage=100)))
    def rates(self):
        return {r:dict(capacity=100,net=0) for r in ('food','water','scrap','metal','electronics')}
    def test_exact_capacity_shared_markers_and_no_credit_limit(self):
        state=self.state();before=copy.deepcopy(state)
        result=storage_status(state,self.rates())
        self.assertTrue(result['food']['full']);self.assertFalse(result['water']['full'])
        for r in ('scrap','metal','electronics'):
            self.assertTrue(result[r]['full']);self.assertEqual(result[r]['used'],100)
            self.assertIn('Shared',result[r]['description'])
        self.assertNotIn('credits',result);self.assertEqual(state,before)
    def test_marker_clears_below_capacity_and_new_capacity_is_used(self):
        state=self.state();state['resources']['scrap']=59
        self.assertFalse(storage_status(state,self.rates())['metal']['full'])
        rates=self.rates();rates['food']['capacity']=150
        self.assertFalse(storage_status(state,rates)['food']['full'])
    def test_overflow_stays_full_with_negative_rate_and_hidden_badge_has_description(self):
        state=self.state();state['resources']['food']=101
        rates=self.rates();rates['food']['net']=-1
        result=storage_status(state,rates)
        self.assertTrue(result['food']['full'])
        self.assertIn('href="#construction"',badge('food',result['food']))
        self.assertIn(' hidden',badge('water',result['water']))

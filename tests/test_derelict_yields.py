"""Public salvage ranges are informative without leaking hidden loot."""
import copy
import unittest
from unittest.mock import patch
from game.building_views import derelict_salvage_label

class DerelictYieldTests(unittest.TestCase):
    def setUp(self):
        self.site=dict(status='untouched',settlement_derelict_id=7,derelict_type='house',
                       random_result='THIS PRIVATE FIELD MUST NOT BE READ')
        self.state=dict(jobs=[],config=dict(derelicts=dict(house=dict(loot=dict(
            food=[4,14],water=[2,10],scrap=[12,28],metal=[0,6],electronics=[0,1])))))
        self.bonus=patch('game.support.best',return_value=0)
        self.bonus.start();self.addCleanup(self.bonus.stop)

    def test_all_material_and_supply_types_show_possible_ranges(self):
        before=copy.deepcopy((self.state,self.site))
        text=derelict_salvage_label(self.state,self.site)
        for expected in ('4–14 Food','2–10 Water','12–28 Scrap','0–6 Metal','0–1 Electronics'):
            self.assertIn(expected,text)
        self.assertEqual((self.state,self.site),before)

    def test_progress_reduces_range_and_bonus_only_affects_materials(self):
        self.site['status']='scavenging'
        self.state['jobs']=[dict(target_derelict_id=7,job_type='scavenging',status='paused',
                                work_completed=50,work_required=100)]
        with patch('game.support.best',return_value=20):
            text=derelict_salvage_label(self.state,self.site)
        self.assertIn('2–7 Food',text)
        self.assertIn('7.2–16.8 Scrap',text)
        self.assertIn('0–0.6 Electronics',text)

    def test_zero_yield_types_omitted_and_cleared_sites_empty(self):
        self.state['config']['derelicts']['house']['loot']['electronics']=[0,0]
        self.assertNotIn('Electronics',derelict_salvage_label(self.state,self.site))
        self.site['status']='cleared'
        self.assertEqual(derelict_salvage_label(self.state,self.site),'No salvage remaining')

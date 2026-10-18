"""Approved Garden output change retains costs, upgrades and citizen safety."""
import unittest
from game.settlement import load_config
from game.economy import utilities
from tests.fixtures import SupportWorld,fixed_map_seed

class GardenOxygenTests(unittest.TestCase):
    @property
    def w(self):
        if not hasattr(self,'_world'):
            with fixed_map_seed():world=SupportWorld(self)
            world.change('enable_consequences')
            self._world=world
        return self._world
    def test_current_catalogue_and_legacy_profile_are_distinct(self):
        info=load_config('prototype_v13')['buildings']['garden'];s=info['levels'][0]
        self.assertFalse(info['oxygen_required']);self.assertFalse(info['electricity_required'])
        self.assertEqual((s['food'],s['oxygen_output'],s['oxygen_demand'],s['radius']),(6,1,0,3))
        self.assertEqual((s['scrap'],s['minutes'],s['workers'],info['max_level']),(35,15,2,1))
        self.assertTrue(load_config('prototype_v10')['buildings']['garden']['oxygen_required'])
    def test_staffing_and_condition_scale_food_and_oxygen(self):
        w=self.w;bid=w.build('garden',x=24,y=18)
        initial=utilities(w.state())
        self.assertNotEqual(initial['buildings'][bid]['reason'],'')
        baseline=initial['capacity']['oxygen']
        w.staff(bid);one=utilities(w.state())
        self.assertEqual(one['buildings'][bid]['outputs']['food'],6)
        self.assertEqual(one['capacity']['oxygen'],baseline+1)
        w.staff(bid);two=utilities(w.state())
        self.assertEqual(two['buildings'][bid]['outputs']['food'],12)
        self.assertEqual(two['capacity']['oxygen'],baseline+2)
        w.sql('UPDATE buildings SET current_hp=75 WHERE building_id=?',(bid,))
        damaged=utilities(w.state())
        self.assertEqual(damaged['buildings'][bid]['outputs']['food'],6)
        self.assertEqual(damaged['capacity']['oxygen'],baseline+1)
    def test_initial_staffing_outside_coverage_keeps_exposure_confirmation(self):
        w=self.w;bid=w.build('garden',x=0,y=0)
        cid=next(c['citizen_id'] for c in w.state()['citizens'] if c['assignment']=='unassigned')
        with self.assertRaisesRegex(ValueError,'outside Oxygen'):
            w.change('worker',building_id=bid,citizen_id=cid)
        w.change('worker',building_id=bid,citizen_id=cid,exposed=True)
        status=utilities(w.state())['buildings'][bid]
        self.assertEqual(status['reason'],'')
        self.assertEqual(status['outputs']['food'],6)

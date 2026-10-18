"""Food crops share Oxygen rules while powered crops keep electricity gates."""
import unittest
from game.settlement import load_config
from game.economy import utilities
from tests.fixtures import SupportWorld,fixed_map_seed

class FoodOxygenTests(unittest.TestCase):
    def test_all_food_building_levels_share_the_small_secondary_output(self):
        config=load_config('prototype_v13')
        for kind in ('garden','greenhouse','hydroponics'):
            info=config['buildings'][kind]
            with self.subTest(kind=kind):
                self.assertFalse(info['oxygen_required'])
                for s in info['levels']:
                    self.assertEqual((s['oxygen_output'],s['oxygen_demand'],s['radius']),(1,0,3))
        for kind in ('greenhouse','hydroponics'):
            self.assertTrue(config['buildings'][kind]['electricity_required'])
            old=load_config('prototype_v12')['buildings'][kind]
            for before,after in zip(old['levels'],config['buildings'][kind]['levels']):
                for key in ('food','workers','scrap','metal','electronics','minutes','hp','food_storage','electricity_demand'):
                    self.assertEqual(before[key],after[key],(kind,key))
        self.assertEqual(config['buildings']['oxygen_garden']['levels'][0]['oxygen_output'],5)
    def test_greenhouse_power_loss_stops_both_outputs(self):
        with fixed_map_seed():w=SupportWorld(self)
        w.change('enable_consequences')
        # Isolate the crop from Town Hall Electricity. Killing a turbine
        # beside Town Hall would leave its normal fallback supply available.
        bid=w.build('greenhouse',x=30,y=18)
        w.build('wind_turbine',x=30,y=15,level=3)
        from game.buildings import coverage
        building=next(b for b in w.state()['buildings'] if b['building_id']==bid)
        self.assertLess(coverage(w.state(),building),w.state()['config']['construction']['coverage_fraction'])
        cid=next(c['citizen_id'] for c in w.state()['citizens'] if c['assignment']=='unassigned')
        w.change('worker',building_id=bid,citizen_id=cid,exposed=True)
        powered=utilities(w.state())
        self.assertEqual(powered['buildings'][bid]['reason'],'')
        self.assertGreater(powered['buildings'][bid]['outputs']['food'],0)
        oxygen=powered['capacity']['oxygen']
        w.sql("UPDATE buildings SET current_hp=0 WHERE building_type='wind_turbine'")
        unpowered=utilities(w.state())
        self.assertIn('electricity',unpowered['buildings'][bid]['reason'].lower())
        self.assertEqual(unpowered['buildings'][bid]['outputs'],{})
        self.assertLess(unpowered['capacity']['oxygen'],oxygen)
    def test_powered_crop_outside_oxygen_keeps_worker_safety_guard(self):
        with fixed_map_seed():w=SupportWorld(self)
        w.change('enable_consequences')
        bid=w.build('hydroponics',x=0,y=0)
        cid=next(c['citizen_id'] for c in w.state()['citizens'] if c['assignment']=='unassigned')
        with self.assertRaisesRegex(ValueError,'outside Oxygen'):
            w.change('worker',building_id=bid,citizen_id=cid)

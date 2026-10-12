import unittest
from game.building_views import map_requires_staff


class PassiveMapStaffTests(unittest.TestCase):
    def test_passive_completed_building_hides_counter_but_production_keeps_it(self):
        building=dict(building_id=2,building_type='house',status='active')
        self.assertFalse(map_requires_staff({'jobs':[]},building,0))
        self.assertTrue(map_requires_staff({'jobs':[]},building,2))

    def test_passive_projects_need_crew_markers_until_complete(self):
        building=dict(building_id=2,building_type='house',status='construction')
        self.assertTrue(map_requires_staff({'jobs':[]},building,0))
        building['status']='active'
        job=dict(target_building_id=2,job_type='repair',status='paused')
        self.assertTrue(map_requires_staff({'jobs':[job]},building,0))
        job['status']='completed'
        self.assertFalse(map_requires_staff({'jobs':[job]},building,0))

    def test_town_hall_and_active_salvage_keep_counters(self):
        self.assertTrue(map_requires_staff({'jobs':[]},dict(building_id=1,building_type='town_hall',status='active'),0))
        building=dict(building_id=2,building_type='house',status='ruined')
        self.assertFalse(map_requires_staff({'jobs':[]},building,0))
        job=dict(target_building_id=2,job_type='building_salvage',status='active')
        self.assertTrue(map_requires_staff({'jobs':[job]},building,0))

"""Display eligibility and assigned-citizen counts without changing gameplay."""
import copy
import unittest
from game.building_views import build_availability, map_staff, staff_badge


class BuildMapFeedbackTests(unittest.TestCase):
    def test_shortages_use_spendable_materials_and_show_each_resource(self):
        state = dict(buildings=[{'level':1}], resources=dict(scrap=20,metal=4,electronics=0),
                     reserved=dict(scrap=15))
        info = dict(unlock=1, levels=[dict(scrap=10,metal=7,electronics=2)])
        self.assertEqual(build_availability(state,info),
                         ['Need 5 more Scrap','Need 3 more Metal','Need 2 more Electronics'])

    def test_exact_cost_is_available_but_town_hall_lock_remains(self):
        state = dict(buildings=[{'level':1}], resources=dict(scrap=10,metal=0,electronics=0))
        info = dict(unlock=1,levels=[dict(scrap=10,metal=0,electronics=0)])
        self.assertEqual(build_availability(state,info),[])
        info['unlock']=2
        self.assertEqual(build_availability(state,info),['Town Hall 2 required'])

    def test_staff_counts_direct_and_job_assignments_once_and_excludes_away(self):
        state = dict(jobs=[dict(job_id=8,status='active',target_building_id=2,target_derelict_id=None)],
            citizens=[dict(building_id=2,job_id=8),dict(building_id=2,job_id=None,away=True),
                      dict(building_id=None,job_id=8),dict(building_id=3,job_id=None)])
        before=copy.deepcopy(state)
        self.assertEqual(map_staff(state,building=2),2)
        self.assertEqual(map_staff(state,building=3),1)
        self.assertEqual(state,before)

    def test_ruin_scavengers_count_only_current_jobs(self):
        state=dict(jobs=[dict(job_id=8,status='paused',target_building_id=None,target_derelict_id=5),
                         dict(job_id=9,status='completed',target_building_id=None,target_derelict_id=5)],
                   citizens=[dict(building_id=None,job_id=8),dict(building_id=None,job_id=9)])
        self.assertEqual(map_staff(state,derelict=5),1)
        self.assertEqual(map_staff(state,derelict=6),0)
        self.assertIn('1 assigned citizens',staff_badge(1,3,4))

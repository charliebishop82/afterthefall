"""Compact labels and project percentages remain presentation-only."""
import copy
import unittest
from unittest.mock import patch
from game.building_views import map_job_badge, map_occupancy, staff_badge


class MapProjectMarkerTests(unittest.TestCase):
    def test_people_marker_has_numeric_text_and_accessible_description(self):
        marker=staff_badge(3,5,6)
        self.assertIn('<circle',marker)
        self.assertIn('3 assigned citizens</title>',marker)
        self.assertIn('font-size=".4">3</text>',marker)
        self.assertIn('pointer-events="none"',marker)

    def test_construction_upgrade_and_repair_progress(self):
        for kind in ('construction','upgrade','repair'):
            with self.subTest(kind=kind):
                state={'jobs':[dict(job_id=7,target_building_id=2,job_type=kind,
                              status='active',work_completed=25,work_required=100)]}
                before=copy.deepcopy(state)
                marker=map_job_badge(state,2,4,5)
                self.assertIn('id="map-job-7"',marker)
                self.assertIn('25%</text>',marker)
                self.assertEqual(map_job_badge(state,3,4,5),'')
                self.assertEqual(state,before)

    def test_completed_and_manufacturing_jobs_do_not_make_project_labels(self):
        state={'jobs':[dict(job_id=7,target_building_id=2,job_type='construction',status='completed'),
                       dict(job_id=8,target_building_id=2,job_type='manufacturing',status='active')]}
        self.assertEqual(map_job_badge(state,2,4,5),'')

    def test_occupancy_keeps_ruins_but_excludes_cleared_land(self):
        state=dict(buildings=[dict(origin_x=1,origin_y=2,status='ruined'),
                              dict(origin_x=9,origin_y=9,status='cleared')],
                   derelicts=[dict(origin_x=5,origin_y=6,status='active',derelict_type='small'),
                              dict(origin_x=8,origin_y=8,status='cleared',derelict_type='small')],
                   config={'derelicts':{'small':{'footprint':[2,3]}}})
        with patch('game.building_views.footprint',return_value=(3,4)):
            self.assertEqual(map_occupancy(state),[dict(x=1,y=2,width=3,height=4),
                                                dict(x=5,y=6,width=2,height=3)])

"""Scavenging uses a decreasing amber marker instead of a build percentage."""
import copy
import unittest
from game.building_views import scavenging_badge


class ScavengingMarkerTests(unittest.TestCase):
    def state(self,done=35,status='active'):
        return {'jobs':[dict(job_id=7,target_derelict_id=2,job_type='scavenging',
                             status=status,work_completed=done,work_required=100)]}

    def test_partial_recovery_has_pickaxe_remaining_bar_and_hover_label(self):
        state=self.state();before=copy.deepcopy(state)
        marker=scavenging_badge(state,2,4,5,2)
        self.assertIn('map-scavenging-7',marker)
        self.assertIn('scavenge-pickaxe',marker)
        self.assertIn('stroke-dasharray="65 100"',marker)
        self.assertIn('Scavenging: 35% recovered</title>',marker)
        self.assertNotIn('map-job',marker)
        self.assertEqual(state,before)

    def test_paused_work_keeps_progress_and_other_sites_have_no_marker(self):
        self.assertIn('stroke-dasharray="65 100"',scavenging_badge(self.state(status='paused'),2,4,5,2))
        self.assertEqual(scavenging_badge(self.state(),9,4,5,2),'')
        self.assertEqual(scavenging_badge({'jobs':[]},2,4,5,2),'')

    def test_progress_is_clamped_and_completed_job_is_removed_on_render(self):
        self.assertIn('stroke-dasharray="100 100"',scavenging_badge(self.state(-1),2,4,5,2))
        self.assertIn('stroke-dasharray="0 100"',scavenging_badge(self.state(101),2,4,5,2))
        self.assertEqual(scavenging_badge(self.state(100,'completed'),2,4,5,2),'')

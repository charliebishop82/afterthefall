"""XP display uses cumulative season thresholds without changing citizen state."""
import copy
import unittest
from game.progression_views import panel

class ProgressionDisplayTests(unittest.TestCase):
    def test_remaining_xp_and_escaped_names_without_mutation(self):
        state={'config':{'progression':{'thresholds':[0,100,250],'work_xp_per_hour':1,'construction_xp_per_hour':2}},'citizens':[{'citizen_id':7,'name':'<Citizen>','level':2,'xp':130}]}
        before=copy.deepcopy(state);html=panel(state)
        self.assertIn('120.00 XP to level 3 (250 total)',html)
        self.assertIn('&lt;Citizen&gt;',html);self.assertIn('value="30"',html)
        self.assertEqual(state,before)

    def test_maximum_level_is_explicit(self):
        state={'config':{'progression':{'thresholds':[0,100],'work_xp_per_hour':1,'construction_xp_per_hour':2}},'citizens':[{'citizen_id':1,'name':'Max','level':2,'xp':200}]}
        self.assertIn('Maximum level',panel(state))

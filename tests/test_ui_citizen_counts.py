import copy
import unittest
from game.ui_counts import citizen_counts


class CitizenCountTests(unittest.TestCase):
    def test_available_excludes_assigned_away_and_incapacitated_citizens(self):
        state={'citizens':[dict(assignment='unassigned',current_hp=10),
            dict(assignment='administrator',current_hp=100),
            dict(assignment='construction',current_hp=100),
            dict(assignment='unassigned',current_hp=10,away=True),
            dict(assignment='unassigned',current_hp=0)]}
        before=copy.deepcopy(state)
        self.assertEqual(citizen_counts(state),{'total':5,'free':1})
        self.assertEqual(state,before)

    def test_empty_roster_has_zero_counts(self):
        self.assertEqual(citizen_counts({'citizens':[]}),{'total':0,'free':0})

    def test_assignment_changes_are_reflected_without_saved_counters(self):
        citizen=dict(assignment='unassigned',current_hp=10)
        state={'citizens':[citizen]}
        self.assertEqual(citizen_counts(state)['free'],1)
        citizen['assignment']='scavenging'
        self.assertEqual(citizen_counts(state)['free'],0)
        self.assertEqual(citizen_counts(state)['total'],1)

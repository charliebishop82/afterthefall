"""Read-only card metadata points to existing controls and own expedition."""
import copy
import unittest
from game.citizen_portal import data

class CitizenPortalTests(unittest.TestCase):
    def citizen(self):return dict(citizen_id=2,name='Alex Ash',level=1,xp=3,current_hp=80,morale=60,assignment='unassigned',building_id=None,job_id=None)
    def state(self):return dict(config=dict(citizen_hp=100,simulation=dict(hp_per_level=8)),settlement=dict(simulation_processed_at=1000),buildings=[],jobs=[],expeditions=[])
    def test_free_injured_citizen_keeps_exact_identity_and_health(self):
        c=self.citizen();state=self.state();before=copy.deepcopy((state,c));card=data(state,c)
        self.assertTrue(card['free']);self.assertEqual(card['max_hp'],100);self.assertEqual(card['id'],2)
        self.assertEqual((state,c),before)
    def test_explorer_targets_own_trip_with_return_estimate(self):
        c=dict(self.citizen(),away=True,exploring=True)
        state=self.state();state['expeditions']=[dict(status='exploring',returns_at=1900,crew=[dict(id=2)])]
        card=data(state,c);self.assertFalse(card['free']);self.assertEqual(card['target'],'#expeditions')
        self.assertEqual(card['return_seconds'],900)
    def test_scavenger_and_raid_links_use_existing_controls(self):
        c=dict(self.citizen(),assignment='scavenging',job_id=7);state=self.state()
        state['jobs']=[dict(job_id=7,target_derelict_id=9)]
        self.assertEqual(data(state,c)['target'],'#derelict-9')
        c['away']=True;self.assertEqual(data(state,c)['target'],'#conflict')

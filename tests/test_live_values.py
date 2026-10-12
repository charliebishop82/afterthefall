"""Read-only live display payloads for existing interface elements."""
import copy
import unittest
from game.web_views import live_values


class LiveValueTests(unittest.TestCase):
    def state(self):
        return dict(resources={'credits':42},
            season=dict(config_version='prototype_v13',status='active',finalization_at=2000),
            settlement=dict(status='active',simulation_processed_at=1000),
            buildings=[dict(building_id=1,building_type='town_hall',level=2,status='active')],
            derelicts=[], jobs=[dict(job_id=7,status='completed',target_building_id=1,target_derelict_id=None)],
            citizens=[dict(citizen_id=3,level=2,xp=4.5,current_hp=80,morale=50,effective_morale=55,
                           assignment='administrator',building_id=1,job_id=None)])

    def test_numbers_and_map_counts_are_current_and_do_not_mutate_state(self):
        state=self.state(); before=copy.deepcopy(state); data=live_values(state)
        self.assertEqual(data['credits'],42)
        self.assertEqual(data['citizens'][0]['morale'],55)
        self.assertEqual(data['citizens'][0]['hp'],80)
        self.assertEqual(data['map_staff'],{'town-hall':1})
        self.assertEqual(data['completed_jobs'],['7'])
        self.assertEqual(data['hall_level'],2)
        self.assertFalse(data['build_locked'])
        self.assertEqual(state,before)

    def test_away_citizen_is_shown_raiding_and_not_counted_at_home(self):
        state=self.state(); state['citizens'][0]['away']=True
        data=live_values(state)
        self.assertEqual(data['citizens'][0]['assignment'],'Raiding')
        self.assertEqual(data['map_staff']['town-hall'],0)

    def test_finalization_and_suspension_keep_construction_closed(self):
        for status,now,settlement in [('finalizing',1000,'active'),('active',2000,'active'),
                                       ('finished',1000,'active'),('active',1000,'suspended')]:
            with self.subTest(status=status,now=now,settlement=settlement):
                state=self.state(); state['season']['status']=status
                state['settlement'].update(status=settlement,simulation_processed_at=now)
                self.assertTrue(live_values(state)['build_locked'])

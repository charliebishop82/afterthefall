import unittest
from unittest.mock import patch
from game.building_views import map_filter_flags
from game.bots import suggested_bot_name


class MapAttentionTests(unittest.TestCase):
    def state(self):
        return dict(season={'status':'active'},settlement={'status':'active'},citizens=[],derelicts=[],
                    buildings=[dict(building_id=2,building_type='house',status='active',current_hp=80)],
                    jobs=[dict(job_id=7,job_type='repair',target_building_id=2,target_derelict_id=None,
                               status='paused',work_completed=0,work_required=100)])

    def test_active_stalled_repair_and_damage_are_separate_flags(self):
        with patch('game.building_views.spec',return_value=dict(workers=0,hp=100)),patch('game.building_views.job_speed',return_value=0):
            flags=map_filter_flags(self.state())['building-2']
        self.assertEqual(flags,dict(unstaffed=True,stalled=True,damaged=True))

    def test_global_pause_is_not_a_stalled_work_warning(self):
        state=self.state();state['season']['status']='paused'
        with patch('game.building_views.spec',return_value=dict(workers=0,hp=100)),patch('game.building_views.job_speed') as speed:
            flags=map_filter_flags(state)['building-2']
        self.assertFalse(flags['stalled']);speed.assert_not_called()

    def test_name_suggestions_avoid_all_account_and_reservation_collisions(self):
        self.assertEqual(suggested_bot_name({'bot_1','other'},{'Bot 2'}),('bot_3','Bot 3'))
        self.assertEqual(suggested_bot_name(set(),set()),('bot_1','Bot 1'))

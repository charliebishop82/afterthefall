"""Military overview respects operational homes and existing combat eligibility."""
import copy
import unittest
from unittest.mock import patch
from game.military_portal import payload

class MilitaryPortalTests(unittest.TestCase):
    def state(self):
        return dict(season=dict(config_version='prototype_v13',status='active'),settlement=dict(status='active',attacks_remaining=3,simulation_processed_at=1000),
            config=dict(citizen_hp=100,simulation=dict(hp_per_level=8),structural={},units={
                'ground_defense_drone':dict(name='Ground drone',hp=100,factory='drone_factory',storage='ground_defense_bay')}),
            citizens=[dict(citizen_id=i,assignment='unassigned',level=1,current_hp=100,integrated=True) for i in range(7)],
            buildings=[dict(building_id=2,building_type='ground_defense_bay',status='active')],
            units=[dict(unit_id=1,unit_type='ground_defense_drone',status='available',current_hp=50,home_building_id=2),
                   dict(unit_id=2,unit_type='ground_defense_drone',status='deployed',current_hp=100,home_building_id=2)],
            jobs=[],inventory=[],expeditions=[])
    def test_stored_damaged_deployed_and_ready_are_distinct(self):
        state=self.state();before=copy.deepcopy(state)
        with patch('game.economy.utilities',return_value={'buildings':{2:{'reason':''}}}):result=payload(state)
        self.assertTrue(result['clock_running'])
        row=result['equipment'][0]
        self.assertEqual((row['total'],row['ready'],row['deployed'],row['damaged']),(2,1,1,1))
        self.assertEqual(result['eligible_raiders'],1);self.assertEqual(state,before)
    def test_failed_home_and_away_citizen_are_not_ready(self):
        state=self.state();state['citizens'][0]['away']=True
        with patch('game.economy.utilities',return_value={'buildings':{2:{'reason':'No electricity'}}}):result=payload(state)
        self.assertEqual(result['equipment'][0]['ready'],0)
        self.assertEqual(result['eligible_raiders'],0)

    def test_clock_stops_for_paused_season_or_suspended_settlement(self):
        for season_status,settlement_status in [('paused','active'),('finished','active'),('active','suspended')]:
            with self.subTest(season=season_status,settlement=settlement_status):
                state=self.state();state['season']['status']=season_status;state['settlement']['status']=settlement_status
                with patch('game.economy.utilities',return_value={'buildings':{2:{'reason':''}}}):result=payload(state)
                self.assertFalse(result['clock_running'])

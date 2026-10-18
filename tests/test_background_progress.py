"""ETA must use real elapsed time and comparable settlement populations."""
import unittest
from game.background_progress import Progress, message, duration


class ProgressTests(unittest.TestCase):
    def rows(self,*hours):
        return [dict(settlement_id=i,behind=value*3600) for i,value in enumerate(hours,1)]

    def test_real_time_speed_and_eta_after_second_sample(self):
        progress=Progress(started_at=0)
        first=progress.sample(self.rows(100,100),at=1)
        self.assertIsNone(first['estimated_remaining_seconds'])
        second=progress.sample(self.rows(95,95),at=16)
        self.assertEqual(second['elapsed_seconds'],16)
        self.assertEqual(second['net_game_hours_per_real_minute'],40)
        self.assertEqual(second['estimated_remaining_seconds'],285)
        self.assertIn('ETA ~4m 45s',message(2,second))

    def test_membership_change_resets_estimate_instead_of_claiming_fast_completion(self):
        progress=Progress(0)
        progress.sample(self.rows(100,100),at=1)
        stats=progress.sample(self.rows(99),at=16)
        self.assertEqual(stats['estimate_status'],'measuring')
        self.assertIsNone(stats['estimated_remaining_seconds'])

    def test_stationary_or_growing_backlog_does_not_get_misleading_eta(self):
        progress=Progress(0)
        progress.sample(self.rows(10),at=1)
        for at,amount in ((16,10),(31,11)):
            stats=progress.sample(self.rows(amount),at=at)
            self.assertEqual(stats['estimate_status'],'backlog_not_shrinking')
            self.assertIsNone(stats['estimated_remaining_seconds'])
            self.assertIn('ETA unavailable',message(1,stats))

    def test_duration_is_explicit_real_time_and_rounds_up(self):
        self.assertEqual(duration(0),'0s')
        self.assertEqual(duration(61),'1m 01s')
        self.assertEqual(duration(3660),'1h 01m')
        self.assertEqual(duration(0.1),'1s')

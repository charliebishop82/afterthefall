"""Diagnostics must distinguish capped excess and actual chosen step boundaries."""
import unittest
from game.calculations import scope, record_limits
from game.background_progress import Progress,message
from game import background
from game.catchup_diagnostics import bulk_blockers
from tests.fixtures import SupportWorld,fixed_map_seed


class StepDiagnosticsTests(unittest.TestCase):
    def test_only_actual_limiting_boundaries_count_and_ties_are_visible(self):
        with scope() as metrics:
            record_limits(1000,1060,[('healing',1060),('work XP',1060),('work XP',1060),('daily rollover',86400)])
            self.assertEqual(metrics['step_limits'],{'healing':1,'work XP':1})
            record_limits(1060,1120,[('healing',1120),('work XP',1120)])
            self.assertEqual(metrics['step_limits'],{'healing':2,'work XP':2})

    def test_grid_alignment_is_visible_when_no_other_boundary_matches(self):
        with scope() as metrics:
            record_limits(1000,1060,[('batch/offline horizon',1067)])
            self.assertEqual(metrics['step_limits'],{'XP minute alignment':1})

    def test_pending_splits_remaining_allowance_from_excess_inactivity(self):
        with fixed_map_seed():w=SupportWorld(self)
        w.change('enable_consequences')
        w.sql('UPDATE settlements SET simulation_processed_at=? WHERE settlement_id=?',(1000+24*3600,w.sa))
        rows=background.pending(w.path,1000+72*3600)
        row=next(r for r in rows if r['settlement_id']==w.sa)
        self.assertEqual(row['simulation_seconds'],24*3600)
        self.assertEqual(row['skip_seconds'],24*3600)
        self.assertEqual(row['behind'],row['simulation_seconds']+row['skip_seconds'])

    def test_eta_uses_remaining_simulation_instead_of_skippable_calendar_hours(self):
        progress=Progress(0)
        first=[dict(settlement_id=1,behind=110*3600,simulation_seconds=10*3600,skip_seconds=100*3600)]
        second=[dict(settlement_id=1,behind=109*3600,simulation_seconds=9*3600,skip_seconds=100*3600)]
        progress.sample(first,at=1)
        stats=progress.sample(second,at=61)
        self.assertEqual(stats['estimated_remaining_seconds'],540)
        self.assertEqual(stats['simulation_game_hours'],9)
        self.assertEqual(stats['skippable_game_hours'],100)
        self.assertIn('9.0h to simulate; 100.0h to skip',message(1,stats))

    def test_skip_only_phase_does_not_promise_zero_second_completion(self):
        stats=Progress(0).sample([dict(settlement_id=1,behind=3600,simulation_seconds=0,skip_seconds=3600)],at=1)
        self.assertIsNone(stats['estimated_remaining_seconds'])
        self.assertEqual(stats['estimate_status'],'skip_phase')
        self.assertIn('skip/shared-clock work pending',message(1,stats))

    def test_paused_job_is_explicitly_reported_as_a_bulk_guard(self):
        with fixed_map_seed():w=SupportWorld(self)
        state=w.state()
        state['jobs'].append({'status':'paused','job_type':'scavenging'})
        self.assertIn('paused scavenging (1)',bulk_blockers(state))

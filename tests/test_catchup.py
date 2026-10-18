"""Batched work must conserve the outcomes of uninterrupted simulation."""
from contextlib import closing
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from database.create_database import connect_database
from game import catchup
from game.settlement import account_scope, read_state
from game.simulation import _advance, advance_settlement
from tests.fixtures import SupportWorld, fixed_map_seed


class CatchupTests(unittest.TestCase):
    def world(self):
        with fixed_map_seed():
            return SupportWorld(self)

    def test_one_interval_commits_and_repeated_batches_match_full_update(self):
        w = self.world()
        # Healing creates genuine minute boundaries. A healthy quiet world
        # may now correctly finish the whole horizon in one bulk interval.
        cid=w.state()['citizens'][1]['citizen_id']
        w.sql('UPDATE citizens SET current_hp=50 WHERE citizen_id=?',(cid,))
        from game.quiet import eligible
        self.assertFalse(eligible(w.state()))
        copy = Path(w.tmp.name)/'comparison.db'
        with closing(connect_database(w.path)) as source, closing(sqlite3.connect(copy)) as target:
            source.backup(target)
        with account_scope(w.a):
            expected = advance_settlement(copy, 2200)
        with closing(connect_database(w.path)) as c, c, account_scope(w.a):
            c.row_factory = sqlite3.Row
            before = read_state(c)['settlement']['simulation_processed_at']
            _advance(c, read_state(c), 2200, max_intervals=1)
            partial = read_state(c)['settlement']['simulation_processed_at']
        self.assertGreater(partial, before)
        self.assertLess(partial, 2200)
        # A newly opened connection sees committed progress; no in-memory job is required.
        for _ in range(100):
            with closing(connect_database(w.path)) as c, c, account_scope(w.a):
                c.row_factory = sqlite3.Row
                current = read_state(c)
                if current['settlement']['simulation_processed_at'] >= 2200:
                    break
                _advance(c, current, 2200, max_intervals=1)
        else:
            self.fail('Catch-up did not make forward progress')
        actual = w.state()
        for resource in ('food','water','scrap','metal','electronics','credits'):
            self.assertAlmostEqual(actual['resources'][resource],expected['resources'][resource],places=7)
        for key in ('citizens','jobs','buildings','xp_clock','recovery_clock','needs_clock','regen_pending'):
            self.assertEqual(actual[key], expected[key], key)

    def test_quiet_single_interval_can_finish_the_horizon(self):
        w=self.world()
        from game.quiet import eligible
        self.assertTrue(eligible(w.state()))
        with closing(connect_database(w.path)) as c,c,account_scope(w.a):
            c.row_factory=sqlite3.Row
            _advance(c,read_state(c),2200,max_intervals=1)
            self.assertEqual(read_state(c)['settlement']['simulation_processed_at'],2200)

    def test_coordinator_limits_horizon_and_releases_write_lock(self):
        w = self.world()
        before = w.state()['settlement']['simulation_processed_at']
        result = catchup.step(w.path,w.a,10000)
        self.assertEqual(result['status'],'catching_up')
        after = w.state()['settlement']['simulation_processed_at']
        self.assertGreater(after,before)
        self.assertLessEqual(after,before+catchup.HORIZON)
        with closing(connect_database(w.path)) as c, c:
            c.execute('BEGIN IMMEDIATE')  # No batch connection holds the lock after returning.

    def test_paused_season_does_not_start_catchup_or_move_clock(self):
        w = self.world()
        w.sql("UPDATE seasons SET status='paused',paused_at=1000")
        self.assertEqual(catchup.status(w.path,w.a,10000)['status'],'ready')
        catchup.step(w.path,w.a,10000)
        self.assertEqual(w.state()['settlement']['simulation_processed_at'],1000)

    def test_failed_batch_rolls_back_instead_of_leaving_partial_steps(self):
        w = self.world()
        def fail(c,state,now,**kwargs):
            c.execute('UPDATE settlements SET simulation_processed_at=2000')
            raise ValueError('Injected failure')
        with patch('game.simulation._advance',side_effect=fail):
            with self.assertRaisesRegex(ValueError,'Injected failure'):
                catchup.step(w.path,w.a,10000)
        self.assertEqual(w.state()['settlement']['simulation_processed_at'],1000)

    def test_live_window_and_clock_backwards_do_not_trigger_catchup(self):
        w = self.world()
        self.assertEqual(catchup.status(w.path,w.a,1000+catchup.LIVE_WINDOW)['status'],'ready')
        self.assertEqual(catchup.status(w.path,w.a,900)['status'],'ready')
        self.assertEqual(catchup.status(w.path,w.a,10000)['status'],'catching_up')


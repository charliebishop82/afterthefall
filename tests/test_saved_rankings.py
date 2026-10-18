"""Viewing standings must not force unrelated offline simulations."""
from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch

from database.create_database import connect_database
from game import catchup, expansion, expansion_views
from game.settlement import account_scope
from tests.fixtures import SupportWorld, fixed_map_seed


class SavedRankingTests(unittest.TestCase):
    def world(self):
        with fixed_map_seed():w=SupportWorld(self)
        with closing(connect_database(w.path)) as c,c,account_scope(w.a):
            c.row_factory=sqlite3.Row
            expansion.enable(c,w.state(),1000)
        return w

    def test_local_catchup_leaves_unrelated_player_clock_unchanged(self):
        w=self.world()
        w.sql('UPDATE settlements SET simulation_processed_at=5000 WHERE settlement_id=?',(w.sa,))
        result=catchup.status(w.path,w.a,5000)
        self.assertEqual(result['status'],'ready')
        self.assertEqual(result['settlements_remaining'],0)
        self.assertEqual(catchup.status(w.path,w.a,5000,shared=True)['status'],'catching_up')
        self.assertEqual(w.state(w.b)['settlement']['simulation_processed_at'],1000)

    def test_rankings_report_snapshot_times_without_advancing_players(self):
        w=self.world()
        w.sql('UPDATE settlements SET simulation_processed_at=1200 WHERE settlement_id=?',(w.sa,))
        with closing(connect_database(w.path)) as c,account_scope(w.a):
            c.row_factory=sqlite3.Row
            with patch('game.simulation._advance') as advance:
                rows=expansion_views.scores(c,w.state())
            advance.assert_not_called()
        clocks={r['settlement_id']:r['processed_at'] for r in rows}
        self.assertEqual(clocks,{w.sa:1200,w.sb:1000})
        self.assertEqual(w.state(w.b)['settlement']['simulation_processed_at'],1000)

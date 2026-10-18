"""Snapshot reuse must reduce reads without returning stale or shared data."""
from contextlib import closing
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from database.create_database import connect_database
from game import simulation
from game.calculations import scope
from game.settlement import account_scope, read_state, load_config
from tests.fixtures import SupportWorld, fixed_map_seed


class StateReuseTests(unittest.TestCase):
    def world(self):
        with fixed_map_seed():w=SupportWorld(self)
        w.change('enable_consequences')
        return w

    def test_reusing_interval_result_matches_forced_reload_with_fewer_reads(self):
        w=self.world();copy=Path(w.tmp.name)/'reload.db'
        with closing(connect_database(w.path)) as source,closing(sqlite3.connect(copy)) as target:
            source.backup(target)
        advance_interval=simulation._advance_interval
        def discard_snapshot(c,state,now):
            advance_interval(c,state,now)
            return None
        with account_scope(w.a),patch('game.quiet.eligible',return_value=False),scope() as old:
            with patch('game.simulation._advance_interval',side_effect=discard_snapshot):
                expected=simulation.advance_settlement(copy,1600)
        with account_scope(w.a),patch('game.quiet.eligible',return_value=False),scope() as new:
            actual=simulation.advance_settlement(w.path,1600)
        self.assertEqual(actual,expected)
        self.assertLess(new['state_reads'],old['state_reads'])
        self.assertGreater(new['rule_snapshot_hits'],0)

    def test_housing_write_invalidates_the_interval_snapshot(self):
        w=self.world();cid=w.state()['citizens'][0]['citizen_id']
        w.sql('UPDATE citizens SET homeless_since=999 WHERE citizen_id=?',(cid,))
        with closing(connect_database(w.path)) as c,c,account_scope(w.a):
            c.row_factory=sqlite3.Row
            result=simulation._advance_interval(c,read_state(c),1060)
            self.assertIsNotNone(result)
            citizen=next(citizen for citizen in result['citizens'] if citizen['citizen_id']==cid)
            self.assertIsNone(citizen['homeless_since'])
            self.assertEqual(result,read_state(c))

    def test_prepared_rules_are_independent_and_version_changes_do_not_reuse_old_rules(self):
        w=self.world()
        with closing(connect_database(w.path)) as c,c,account_scope(w.a),scope() as metrics:
            c.row_factory=sqlite3.Row
            first=read_state(c)
            original=first['config']['buildings']['garden']['name']
            first['config']['buildings']['garden']['name']='fixture mutation'
            second=read_state(c)
            self.assertEqual(second['config']['buildings']['garden']['name'],original)
            self.assertGreater(metrics['rule_snapshot_hits'],0)
            c.execute("UPDATE seasons SET config_version='prototype_v12'")
            third=read_state(c)
            self.assertEqual(third['config'],load_config('prototype_v12'))

"""One auxiliary read connection per refresh, preserving complete response values."""
from contextlib import ExitStack
import sqlite3
import unittest
from unittest.mock import patch

from game import web_views, trading, combat, communication, equipment_market, market, bot_military, operation_results
from game.read_queries import read_connection
from tests.fixtures import baseline_world
from tests.test_refresh_reuse import expanded_world


class RefreshSnapshotTests(unittest.TestCase):
    def setUp(self):self.world=baseline_world(self,'refresh-snapshot',expanded_world)

    def test_complete_payload_matches_independent_connections_and_is_read_only(self):
        w=self.world;state=w.state();before=w.path.read_bytes()
        with patch('game.read_queries.sqlite3.connect',wraps=sqlite3.connect) as connect:
            shared=web_views.resources(w.path,state,1000)
        self.assertEqual(connect.call_count,1)
        self.assertIn('mode=ro',connect.call_args.args[0])
        # Make each reader open its own snapshot, as before consolidation.
        def independent(path,connection=None,*,rows=False):
            return read_connection(path,rows=rows)
        with ExitStack() as stack:
            for module in (web_views,trading,combat,communication,equipment_market,market,bot_military,operation_results):
                stack.enter_context(patch.object(module,'read_connection',side_effect=independent))
            with patch('game.read_queries.sqlite3.connect',wraps=sqlite3.connect) as connect:
                separate=web_views.resources(w.path,w.state(),1000)
        self.assertGreater(connect.call_count,1)
        self.assertEqual(shared,separate)
        self.assertEqual(w.path.read_bytes(),before)

    def test_reader_failure_closes_snapshot_and_later_refresh_succeeds(self):
        w=self.world;opened=[];original=sqlite3.connect
        def connect(*args,**kwargs):
            c=original(*args,**kwargs);opened.append(c);return c
        state=w.state()
        with patch('game.read_queries.sqlite3.connect',side_effect=connect), \
             patch.object(web_views.market,'public_snapshot',side_effect=ValueError('reader failure')):
            with self.assertRaisesRegex(ValueError,'reader failure'):
                web_views.resources(w.path,state,1000)
        self.assertEqual(len(opened),1)
        with self.assertRaises(sqlite3.ProgrammingError):opened[0].execute('SELECT 1')
        result=web_views.resources(w.path,w.state(),1000)
        self.assertEqual(result['settlement_id'],w.sa)

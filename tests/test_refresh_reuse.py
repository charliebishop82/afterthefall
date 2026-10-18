"""Refresh-local ranking reuse must preserve output and never outlive a request."""
from contextlib import closing
import sqlite3
import unittest
from unittest.mock import patch

from database.create_database import connect_database
from game import expansion, expansion_views, web_views
from game.settlement import account_scope
from tests.fixtures import SupportWorld, baseline_world


def expanded_world(owner):
    world=SupportWorld(owner)
    with account_scope(world.a), closing(connect_database(world.path)) as c,c:
        c.row_factory=sqlite3.Row
        expansion.enable(c,world.state(),1000)
    return world


class RefreshReuseTests(unittest.TestCase):
    def setUp(self):
        self.world=baseline_world(self,'refresh-rankings',expanded_world)

    def test_complete_payload_matches_independent_ranking_calculations(self):
        w=self.world;state=w.state();before=w.path.read_bytes()
        original_revision=web_views.revision
        with patch.object(expansion_views,'scores',wraps=expansion_views.scores) as calculate:
            actual=web_views.resources(w.path,state,1000)
            self.assertEqual(calculate.call_count,1)
        # Reproduce the independent revision calculation used before reuse.
        def independent(path,state,now,**kwargs):
            return original_revision(path,state,now)
        with patch.object(web_views,'revision',side_effect=independent), \
             patch.object(expansion_views,'scores',wraps=expansion_views.scores) as calculate:
            expected=web_views.resources(w.path,w.state(),1000)
            self.assertEqual(calculate.call_count,2)
        self.assertEqual(actual,expected)
        self.assertEqual(w.path.read_bytes(),before)

    def test_next_request_reads_other_players_changes(self):
        w=self.world
        first=web_views.resources(w.path,w.state(),1000)
        w.sql('UPDATE settlements SET settlement_name=? WHERE settlement_id=?',('Renamed settlement',w.sb))
        with patch.object(expansion_views,'scores',wraps=expansion_views.scores) as calculate:
            second=web_views.resources(w.path,w.state(),1000)
        self.assertEqual(calculate.call_count,1)
        self.assertNotEqual(first['scores'],second['scores'])
        other=next(row for row in second['scores'] if row['settlement_id']==w.sb)
        self.assertEqual(other['name'],'Renamed settlement')

    def test_revision_reuse_preserves_financial_changes_and_fallback(self):
        w=self.world;state=w.state();board=web_views.scores(w.path,state)
        old=web_views.revision(w.path,state,1000,ranked_scores=board)
        loan=dict(loan_id=99,outstanding_balance=123,status='active')
        with patch.object(web_views.banking,'loans',return_value=[loan]), \
             patch.object(expansion_views,'scores',side_effect=AssertionError('duplicate rankings')):
            updated=web_views.revision(w.path,state,1000,ranked_scores=board)
        self.assertNotEqual(old,updated)
        self.assertEqual(old,web_views.revision(w.path,state,1000))

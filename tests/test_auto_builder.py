"""Safe first-builder assignment is atomic and does not steal existing workers."""
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from database.create_database import connect_database
from flask_app import game_action
from game.buildings import change_building
from game.settlement import create_settlement, prepare_database, read_settlement


class AutoBuilderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'test.db';prepare_database(self.path)
        create_settlement(self.path,'Builder test',now=1000)

    def build(self,**changes):
        args=dict(building_type='garden',x=21,y=18,now=1000,auto_builder=True)
        args.update(changes)
        return change_building(self.path,'build',**args)

    def test_one_available_builder_is_assigned_and_administrator_stays(self):
        before=read_settlement(self.path)
        expected=min(c['citizen_id'] for c in before['citizens'] if c['assignment']=='unassigned')
        after=self.build();site=after['buildings'][-1]
        builders=[c for c in after['citizens'] if c['assignment']=='construction']
        self.assertEqual(len(builders),1)
        self.assertEqual(builders[0]['citizen_id'],expected)
        self.assertEqual(builders[0]['building_id'],site['building_id'])
        self.assertEqual(sum(c['assignment']=='administrator' for c in after['citizens']),1)
        self.assertEqual(builders[0]['job_id'],after['jobs'][-1]['job_id'])

    def test_no_eligible_citizen_keeps_placed_site_unstaffed(self):
        with closing(connect_database(self.path)) as c,c:
            c.execute("UPDATE citizens SET current_hp=0 WHERE citizen_id NOT IN (SELECT citizen_id FROM citizen_assignments WHERE assignment_type='administrator' AND ended_at IS NULL)")
        after=self.build()
        self.assertEqual(after['buildings'][-1]['status'],'construction')
        self.assertFalse(any(c['assignment']=='construction' for c in after['citizens']))

    def test_unsafe_oxygen_site_does_not_automatically_expose_a_citizen(self):
        after=self.build(x=0,y=0)
        self.assertEqual(after['buildings'][-1]['status'],'construction')
        self.assertFalse(any(c['assignment']=='construction' for c in after['citizens']))

    def test_rejected_build_does_not_assign_or_spend(self):
        with closing(connect_database(self.path)) as c,c:
            c.execute('UPDATE settlement_resources SET scrap=0,metal=0,electronics=0')
        before=read_settlement(self.path)
        with self.assertRaises(ValueError):self.build()
        self.assertEqual(read_settlement(self.path),before)

    def test_player_build_route_requests_automatic_staffing(self):
        with patch('game.buildings.change_building') as change:
            game_action(self.path,'/buildings',dict(action=['build'],building_type=['garden'],x=['21'],y=['18']),1000)
        self.assertTrue(change.call_args.kwargs['auto_builder'])

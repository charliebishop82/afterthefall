"""Provisions, away status, recall, pause and exactly-once returns."""
from contextlib import closing
import json
import sqlite3
import unittest
from database.create_database import connect_database
from game import expeditions
from game.settlement import account_scope,read_state
from game.simulation import advance_settlement,resource_rates
from tests import test_social as fixtures

class ExpeditionTests(unittest.TestCase):
    setUp=fixtures.SocialTests.setUp
    sql=fixtures.SocialTests.sql
    state=fixtures.SocialTests.state
    player=fixtures.SocialTests.player
    def launch(self,food=3,water=3,ids=None):
        ids=ids or [next(c['citizen_id'] for c in self.state(self.a)['citizens'] if c['assignment']=='unassigned')]
        with account_scope(self.a):return expeditions.command(self.path,'launch',1000,citizen_ids=ids,food=food,water=water)
    def advance(self,now):
        with account_scope(self.a):return advance_settlement(self.path,now)
    def row(self):return self.state(self.a)['expeditions'][0]
    def test_packed_supplies_deducted_and_explorer_not_consuming_at_home(self):
        before=self.state(self.a);rates=resource_rates(before)
        self.launch();after=self.state(self.a)
        self.assertEqual(after['resources']['food'],before['resources']['food']-3)
        self.assertEqual(after['resources']['water'],before['resources']['water']-3)
        self.assertEqual(sum(bool(c.get('exploring')) for c in after['citizens']),1)
        self.assertEqual(resource_rates(after)['food']['consumption'],rates['food']['consumption']-1)
        self.assertEqual(self.row()['returns_at'],11800)
    def test_natural_return_yield_and_repeat_read_does_not_duplicate_delivery(self):
        self.launch();returned=self.advance(11800)
        row=returned['expeditions'][0];delivered=json.loads(row['delivered'])
        self.assertEqual(row['status'],'returned');self.assertAlmostEqual(delivered['scrap'],5.5)
        self.assertAlmostEqual(delivered['metal'],1.375)
        self.assertFalse(any(c.get('exploring') for c in returned['citizens']))
        self.assertEqual(self.advance(11800)['resources'],returned['resources'])
        self.assertEqual(self.sql("SELECT count(*) FROM notifications WHERE account_id=? AND notification_type='expedition_return'",(self.a,))[0][0],1)
    def test_recall_stops_gathering_and_returns_unused_provisions(self):
        eid=self.launch()
        with account_scope(self.a):expeditions.command(self.path,'recall',2800,expedition_id=eid)
        self.assertEqual(self.row()['returns_at'],3700)
        self.assertTrue(any(c.get('exploring') for c in self.advance(3699)['citizens']))
        row=self.advance(3700)['expeditions'][0];delivered=json.loads(row['delivered'])
        self.assertAlmostEqual(delivered['scrap'],1)
        self.assertAlmostEqual(delivered['food'],2.25)
        with account_scope(self.a),self.assertRaises(ValueError):expeditions.command(self.path,'recall',3700,expedition_id=eid)
    def test_higher_level_yields_more_and_limiting_provision_sets_duration(self):
        cid=next(c['citizen_id'] for c in self.state(self.a)['citizens'] if c['assignment']=='unassigned')
        self.sql('UPDATE citizens SET level=3 WHERE citizen_id=?',(cid,))
        self.launch(food=4,water=2,ids=[cid])
        self.assertEqual(self.row()['returns_at'],8200)
        self.assertAlmostEqual(json.loads(self.row()['yields'])['scrap'],2.4)
    def test_invalid_duplicate_busy_reserved_and_other_owner_are_rejected(self):
        cid=next(c['citizen_id'] for c in self.state(self.a)['citizens'] if c['assignment']=='unassigned')
        with self.assertRaises(ValueError):self.launch(ids=[cid,cid])
        with self.assertRaises(ValueError):self.launch(food=0)
        with self.assertRaises(ValueError):self.launch(food=1_000_001)
        eid=self.launch(ids=[cid])
        with self.assertRaises(ValueError):self.launch(ids=[cid])
        with account_scope(self.b),self.assertRaises(ValueError):expeditions.command(self.path,'recall',1000,expedition_id=eid)
        self.assertEqual(self.sql('SELECT count(*) FROM waste_expeditions'),[(1,)])
    def test_storage_overflow_reported_without_removing_existing_stock(self):
        self.launch();self.sql('UPDATE settlement_resources SET scrap=250,metal=0,electronics=0 WHERE settlement_id=?',(self.sa,))
        row=self.advance(11800)['expeditions'][0]
        self.assertEqual(json.loads(row['delivered'])['scrap'],0)
        self.assertAlmostEqual(json.loads(row['discarded'])['scrap'],5.5)
        self.assertEqual(self.state(self.a)['resources']['scrap'],250)
    def test_pause_shift_preserves_duration_and_yield(self):
        self.launch()
        with account_scope(self.a),closing(connect_database(self.path)) as c,c:
            c.row_factory=sqlite3.Row;state=read_state(c)
            expeditions.shift_clock(c,state,3600)
        row=self.row();self.assertEqual(row['started_at'],4600);self.assertEqual(row['returns_at'],15400)
        self.assertEqual(row['gather_until']-row['started_at'],9900)
    def test_finalization_rejects_launch_and_rollback_preserves_supplies(self):
        before=self.state(self.a)['resources']
        self.sql('UPDATE seasons SET finalization_at=1000')
        with self.assertRaises(ValueError):self.launch()
        self.assertEqual(self.state(self.a)['resources'],before)
    def test_packed_supplies_cannot_spend_a_direct_trade_reservation(self):
        from game import trading
        with account_scope(self.a):
            trading.transact(self.path,'propose',1000,recipient_id=self.sb,
                             offered={'food':120},requested={'credits':1})
        before=self.state(self.a)['resources']
        with self.assertRaises(ValueError):self.launch()
        self.assertEqual(self.state(self.a)['resources'],before)
    def test_launch_failure_rolls_back_provisions_and_crew(self):
        before=self.state(self.a)
        self.sql("CREATE TRIGGER reject_expedition BEFORE INSERT ON waste_expedition_citizens BEGIN SELECT RAISE(ABORT,'fixture'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.launch()
        self.assertEqual(self.state(self.a),before)
        self.assertEqual(self.sql('SELECT count(*) FROM waste_expeditions'),[(0,)])
    def test_capacity_label_explains_shared_storage(self):
        from game.storage_display import capacity_label
        self.assertIn('230 / 250 shared',capacity_label('metal',dict(used=230,capacity=250,description='Shared materials')))
        self.assertNotIn('shared',capacity_label('food',dict(capacity=150,description='Food')))

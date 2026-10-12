"""Disposable rations, shortage recovery and health boundaries."""
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
import sqlite3

from database.create_database import connect_database
from game import accounts,needs,trading
from game.settlement import account_scope,read_settlement
from game.simulation import advance_settlement,resource_rates


class NeedsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'needs.db';accounts.prepare(self.path)
        self.a=self.sql("INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES ('alpha','!','alpha',1000) RETURNING account_id")[0][0]
        self.sid=accounts.join(self.path,self.a,'Alpha',1000)
        self.sql('DELETE FROM settlement_derelicts');self.sql('DELETE FROM season_derelicts')
    def sql(self,query,args=()):
        with closing(connect_database(self.path)) as c,c:return c.execute(query,args).fetchall()
    def state(self):
        with account_scope(self.a):return read_settlement(self.path)
    def action(self,action='enable',now=1000,**args):
        with account_scope(self.a):return needs.command(self.path,action,now,**args)
    def advance(self,now):
        with account_scope(self.a):return advance_settlement(self.path,now)
    def no_production(self):
        self.sql("UPDATE citizen_assignments SET ended_at=1000,end_reason='test_fixture'")
    def test_rations_consumption_and_current_modifier_restore_without_accumulation(self):
        self.action();before=self.state()
        state=self.action('rations',food='reduced',water='emergency')
        rates=resource_rates(state)
        self.assertEqual(rates['food']['consumption'],4.5);self.assertAlmostEqual(rates['water']['consumption'],3.6)
        self.assertEqual(state['citizens'][0]['morale'],60)
        self.assertEqual(state['citizens'][0]['effective_morale'],45)
        self.assertEqual(state,self.state())
        self.action('rations',food='full',water='full')
        self.assertEqual(self.state()['citizens'],before['citizens'])
    def test_water_grace_boundary_then_four_hp_hour_no_freeze(self):
        self.action();self.no_production();self.sql('UPDATE settlement_resources SET water=0')
        state=self.advance(8200)
        self.assertEqual(state['settlement']['status'],'active')
        self.assertEqual(state['citizens'][0]['current_hp'],100)
        state=self.advance(11800)
        self.assertAlmostEqual(state['citizens'][0]['current_hp'],96)
        self.assertEqual(state['resources']['water'],0)
    def test_food_grace_then_two_hp_hour_combined_shortage_adds(self):
        self.action();self.no_production();self.sql('UPDATE settlement_resources SET food=0,water=0')
        state=self.advance(26200)
        self.assertAlmostEqual(state['citizens'][0]['current_hp'],78)
        self.assertEqual(state['settlement']['simulation_processed_at'],26200)
    def test_partial_production_reduces_damage_and_sufficient_supply_ends_it(self):
        self.action();self.sql('UPDATE settlement_resources SET water=0')
        state=self.advance(8260)
        # The healthy Administrator supplies 2 of the required 6 Water/hour.
        damaged=100-4/60*(1-2/6)
        self.assertAlmostEqual(state['citizens'][1]['current_hp'],damaged,places=4)
        self.sql('UPDATE settlement_resources SET water=100')
        state=self.advance(8320)
        self.assertIsNone(state['needs_clock']['since']['water'])
        self.assertGreater(state['citizens'][1]['current_hp'],damaged)
    def test_empty_stock_with_enough_production_is_not_a_shortage(self):
        self.action();self.sql("UPDATE citizens SET status='dead',current_hp=0 WHERE citizen_id!=1")
        self.sql('UPDATE settlement_resources SET food=0,water=0')
        state=self.advance(1060)
        self.assertEqual(needs.shortages(state),{'food':False,'water':False})
        self.assertEqual(state['citizens'][0]['current_hp'],100)
        self.assertGreater(state['resources']['food'],0)
    def test_reservations_are_not_consumed_to_avoid_shortage(self):
        self.action();self.no_production()
        other=self.sql("INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES ('bravo','!','bravo',1000) RETURNING account_id")[0][0]
        recipient=accounts.join(self.path,other,'Bravo',1000)
        self.sql("INSERT INTO trade_proposals(season_id,proposer_settlement_id,recipient_settlement_id,status,proposed_at,expires_at) VALUES (1,1,?,'pending',1000,87400)",(recipient,))
        self.sql("INSERT INTO resource_reservations(settlement_id,resource_type,quantity,trade_proposal_id,created_at) VALUES (1,'water',120,1,1000)")
        state=self.advance(11800)
        self.assertEqual(state['resources']['water'],120)
        self.assertEqual(trading.available(state,'water'),0)
        self.assertAlmostEqual(state['citizens'][0]['current_hp'],96)
    def test_enabling_existing_supply_freeze_does_not_damage_offline_time(self):
        self.sql('UPDATE settlement_resources SET food=.01')
        frozen=self.advance(1060);self.assertEqual(frozen['settlement']['status'],'suspended')
        state=self.action(now=200000)
        self.assertEqual(state['settlement']['status'],'active')
        self.assertEqual(state['settlement']['simulation_processed_at'],200000)
        self.assertEqual(state['citizens'][0]['current_hp'],100)
        self.assertEqual(state['needs_clock']['since']['food'],200000)
    def test_administrative_suspension_cannot_be_enabled_or_resumed(self):
        self.sql("UPDATE settlements SET status='suspended',suspended_at=1000")
        with self.assertRaisesRegex(ValueError,'Administrative'):self.action(now=1060)
        self.assertEqual(self.state()['settlement']['status'],'suspended')
    def test_invalid_rations_roll_back_all_state(self):
        self.action();before=self.state()
        with self.assertRaises(ValueError):self.action('rations',now=1060,food='invalid')
        self.assertEqual(before,self.state())
    def test_shortage_death_preserves_history_and_replaces_administrator(self):
        self.action();self.sql('UPDATE citizens SET current_hp=1 WHERE citizen_id=1');self.sql('UPDATE settlement_resources SET water=0')
        state=self.advance(11800)
        self.assertNotIn(1,[c['citizen_id'] for c in state['citizens']])
        self.assertEqual(self.sql('SELECT status,death_cause FROM citizens WHERE citizen_id=1'),[('dead','supply_shortage')])
        self.assertIsNotNone(self.sql('SELECT left_at FROM citizen_settlement_history WHERE citizen_id=1')[0][0])
        self.assertEqual(sum(c['assignment']=='administrator' for c in state['citizens']),1)
        self.assertEqual(state['settlement']['status'],'active')
    def test_offline_and_small_steps_identical_and_repeat_idempotent(self):
        self.action();self.no_production();self.sql('UPDATE settlement_resources SET water=0')
        other=Path(self.tmp.name)/'copy.db'
        with closing(connect_database(self.path)) as a,closing(sqlite3.connect(other)) as b:a.backup(b)
        long=self.advance(11800)
        for now in range(1600,11801,600):
            with account_scope(self.a):short=advance_settlement(other,now)
        self.assertEqual(long,short);self.assertEqual(long,self.advance(11800))

    def test_traded_water_stops_damage_and_healing_resumes(self):
        self.action();self.no_production();self.sql('UPDATE settlement_resources SET water=0')
        state=self.advance(11800);hp=state['citizens'][0]['current_hp']
        donor=self.sql("INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES ('donor','!','donor',11800) RETURNING account_id")[0][0]
        accounts.join(self.path,donor,'Donor',11800)
        with account_scope(donor):tid=trading.transact(self.path,'propose',11800,recipient_id=self.sid,offered={'water':10},requested={'credits':1})
        with account_scope(self.a):trading.transact(self.path,'accept',11800,trade_id=tid)
        state=self.advance(11860)
        self.assertIsNone(state['needs_clock']['since']['water'])
        self.assertGreater(state['citizens'][0]['current_hp'],hp)
        self.assertEqual(state['settlement']['status'],'active')

    def test_raiders_do_not_receive_home_shortage_damage(self):
        from game import combat
        self.action();self.no_production()
        other=self.sql("INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES ('bravo','!','bravo',1000) RETURNING account_id")[0][0]
        target=accounts.join(self.path,other,'Bravo',1000)
        self.sql('UPDATE settlements SET protection_until=1000')
        cid=self.sql("INSERT INTO citizens(settlement_id,original_settlement_id,name,sex,current_hp,morale,status,created_at) VALUES (1,1,'Raider Test','unknown',100,60,'alive',1000) RETURNING citizen_id")[0][0]
        with account_scope(self.a):
            combat.command(self.path,'declare',1000,target_id=target)
            combat.command(self.path,'launch',4600,target_id=target,citizen_ids=[cid])
        self.sql('UPDATE settlement_resources SET water=0 WHERE settlement_id=1')
        # The fixture has already exhausted its Water grace before departure.
        clock=self.state()['needs_clock'];clock['since']['water']=-2600
        self.sql("INSERT INTO game_events(season_id,settlement_id,event_type,occurred_at,event_data) VALUES (1,1,'prototype_needs_clock',4600,?)",(json.dumps(clock),))
        state=self.advance(8140)
        raider=next(c for c in state['citizens'] if c['citizen_id']==cid)
        self.assertTrue(raider['away']);self.assertEqual(raider['current_hp'],100)
        self.assertTrue(all(c['current_hp'] < 100 for c in state['citizens'] if not c['away']))
        self.assertEqual(resource_rates(state)['water']['consumption'],6)

    def test_midnight_replenishes_citizens_after_shortage_deaths(self):
        self.action();self.no_production();self.sql('UPDATE settlement_resources SET water=0')
        self.sql('UPDATE citizens SET current_hp=1')
        state=self.advance(86400)
        self.assertEqual(len(state['citizens']),6)
        self.assertTrue(all(c['current_hp']==100 for c in state['citizens']))
        self.assertEqual(self.sql("SELECT count(*) FROM citizens WHERE status='dead'"),[(6,)])

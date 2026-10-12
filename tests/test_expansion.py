"""Expansion integration checks on disposable settlements, with fixed clocks."""
from contextlib import closing
import json
import random
import sqlite3
import unittest
from unittest.mock import patch
from tests.fixtures import CombatWorld
from database.create_database import connect_database
from game import accounts,alliance,banking,capture,combat,expansion,vaults
from game.settlement import account_scope,read_state


class ExpansionTests(unittest.TestCase):
    def setUp(self):
        self.w=CombatWorld(self)
        with account_scope(self.w.a):expansion.transact(self.w.path,'enable',1000)

    def connection(self):
        c=connect_database(self.w.path);c.row_factory=sqlite3.Row;self.addCleanup(c.close)
        return c

    def test_activation_idempotent_and_late_join_funds_once(self):
        w=self.w;before=w.state(w.a)
        with account_scope(w.a):expansion.transact(w.path,'enable',1000)
        self.assertEqual(before,w.state(w.a))
        self.assertEqual(w.sql("SELECT count(*) FROM game_events WHERE event_type='bank_reserve_funded'")[0][0],2)
        w.player('charlie')
        self.assertTrue(w.state(w.a)['expansion'])
        self.assertEqual(w.sql("SELECT count(*) FROM game_events WHERE event_type='bank_reserve_funded'")[0][0],3)

    def test_allied_fraction_rounds_down_per_partner(self):
        self.assertEqual(alliance.quotas({1:[1,2,3],2:[4,5,6]}),{1:[],2:[]})
        self.assertEqual(alliance.quotas({1:list(range(9))})[1],[0,1])

    def test_even_allied_draw_and_rotation(self):
        pools={1:['a','b'],2:['c','d'],3:['e','f']}
        self.assertEqual(alliance.evenly(pools,4),[(1,'a'),(2,'c'),(3,'e'),(1,'b')])
        self.assertEqual(alliance.evenly(pools,2,1),[(2,'c'),(3,'e')])

    def test_duplicate_defense_treaties_do_not_stack_or_chain(self):
        w=self.w;cc,sc=w.player('charlie');dd,sd=w.player('delta')
        for a,b,kind in ((w.sb,sc,'mutual_defense'),(w.sb,sc,'full_defense'),(sc,sd,'full_defense')):
            a,b=sorted((a,b));w.sql("INSERT INTO treaties(season_id,settlement_a_id,settlement_b_id,treaty_type,status,proposer_settlement_id,proposed_at,accepted_at,effective_at) VALUES (1,?,?,?,'active',?,1000,1000,1000)",(a,b,kind,a))
        c=self.connection()
        with c,account_scope(w.b):
            allies=alliance.partners(c,read_state(c),w.sa,1000)
            self.assertEqual([a['settlement']['settlement_id'] for a in allies],[sc])

    def test_defense_treaty_does_not_replace_peace(self):
        w=self.w;a,b=sorted((w.sa,w.sb))
        w.sql("INSERT INTO treaties(season_id,settlement_a_id,settlement_b_id,treaty_type,status,proposer_settlement_id,proposed_at,effective_at) VALUES (1,?,?,'mutual_defense','active',?,1000,1000)",(a,b,a))
        c=self.connection()
        self.assertFalse(combat.blocked(c,w.state(w.a),w.state(w.b),1000))

    def test_ally_that_suspends_during_catchup_does_not_contribute(self):
        w=self.w;cc,sc=w.player('charlie');a,b=sorted((w.sb,sc));c=self.connection()
        with c,account_scope(w.b):
            c.execute("INSERT INTO treaties(season_id,settlement_a_id,settlement_b_id,treaty_type,status,proposer_settlement_id,proposed_at,effective_at) VALUES (1,?,?,'full_defense','active',?,1000,1000)",(a,b,a))
            c.execute('UPDATE settlement_resources SET food=0 WHERE settlement_id=?',(sc,))
            c.execute('UPDATE citizen_assignments SET ended_at=1000 WHERE settlement_id=?',(sc,))
            self.assertEqual(alliance.partners(c,read_state(c),w.sa,1100),[])
            self.assertEqual(c.execute('SELECT status FROM settlements WHERE settlement_id=?',(sc,)).fetchone()[0],'suspended')

    def test_capture_preserves_identity_health_and_excludes_deployed(self):
        w=self.w;aid,ids=w.launch(count=1,objective='population',level=10)
        c=self.connection()
        with c,account_scope(w.a):
            attack=c.execute('SELECT * FROM attacks WHERE attack_id=?',(aid,)).fetchone()
            old=w.state(w.b);citizen=old['citizens'][1];before=dict(citizen)
            with patch('game.capture.choose',return_value=[citizen]):
                got=capture.resolve(c,attack,read_state(c),old,'attacker_win',set(ids),set(),4600,random.Random(1))
            self.assertEqual(len(got),1)
            row=c.execute('SELECT * FROM citizens WHERE citizen_id=?',(citizen['citizen_id'],)).fetchone()
            self.assertEqual((row['name'],row['level'],row['current_hp']),(before['name'],before['level'],before['current_hp']))
            self.assertEqual((row['settlement_id'],row['integrated'],row['morale']),(w.sa,0,20))
            self.assertEqual(c.execute('SELECT count(*) FROM citizen_settlement_history WHERE citizen_id=? AND left_at IS NULL',(row['citizen_id'],)).fetchone()[0],1)

    def test_capture_roll_cap(self):
        self.assertEqual(capture.choose(list(range(10)),1,random.Random(1),3),[0,1,2])
        self.assertEqual(capture.choose(list(range(10)),0,random.Random(1),3),[])

    def test_credit_raid_ignores_capacity_and_preserves_reservations(self):
        w=self.w;c=self.connection()
        with c,account_scope(w.a):
            one=read_state(c)
            with account_scope(w.b):two=read_state(c)
            two['reserved']['credits']=100
            amount=vaults.raid(c,one,two,{'attack_id':99},1000,focused=True)
            self.assertEqual(amount,80)
            self.assertEqual(c.execute('SELECT sum(amount) FROM credit_transactions WHERE transfer_ref=?',('credit-raid:99',)).fetchone()[0],0)

    def test_vault_protection_at_one_hp(self):
        w=self.w;c=self.connection()
        with c,account_scope(w.b):
            state=read_state(c);hall=state['buildings'][0]
            c.execute("INSERT INTO buildings(settlement_id,building_type,level,origin_x,origin_y,current_hp,status,created_at,completed_at) VALUES (?,'vault',1,?,?,1,'active',1000,1000)",(w.sb,hall['origin_x']+2,hall['origin_y']))
            state=read_state(c);alloc=vaults.allocations(state)
            self.assertEqual(sum(a['protected'] for a in alloc.values()),500)

    def test_multiple_destroyed_vaults_do_not_reallocate_same_credits(self):
        w=self.w;c=self.connection()
        with c,account_scope(w.b):
            state=read_state(c);hall=state['buildings'][0];bids=[]
            c.execute('UPDATE settlement_resources SET credits=1000 WHERE settlement_id=?',(w.sb,))
            for offset in (2,4):
                bids.append(c.execute("INSERT INTO buildings(settlement_id,building_type,level,origin_x,origin_y,current_hp,status,created_at,completed_at) VALUES (?,'vault',1,?,?,700,'active',1000,1000)",(w.sb,hall['origin_x']+offset,hall['origin_y'])).lastrowid)
            exposed=0
            for bid in bids:
                damage=vaults.destroyed(c,read_state(c),bid,999,1000)
                exposed+=damage['exposed']
                self.assertEqual(damage['lost'],125)
                c.execute("UPDATE buildings SET status='ruined',current_hp=0 WHERE building_id=?",(bid,))
            self.assertEqual(exposed,500)
            two=read_state(c)
            with account_scope(w.a):one=read_state(c)
            self.assertEqual(vaults.raid(c,one,two,{'attack_id':999},1000,exposed),500)
            self.assertEqual(c.execute('SELECT credits FROM settlement_resources WHERE settlement_id=?',(w.sb,)).fetchone()[0],250)

    def test_liquidation_uses_hardware_then_investments_before_resources(self):
        w=self.w;c=self.connection()
        with c,account_scope(w.a):
            state=read_state(c);lid=banking.borrow(c,state,50,1000)
            banking.invest(c,read_state(c),40,3,1000)
            home=state['buildings'][0]['building_id']
            c.execute("INSERT INTO military_units(settlement_id,unit_type,current_hp,home_building_id,status,created_at) VALUES (?,'offensive_drone',100,?,'available',1000)",(w.sa,home))
            c.execute("UPDATE bank_loans SET outstanding_balance=100,status='liquidating' WHERE loan_id=?",(lid,))
            c.execute('UPDATE settlement_resources SET credits=0 WHERE settlement_id=?',(w.sa,))
            before=read_state(c)['resources']
            banking.liquidate(c,read_state(c),1001)
            self.assertEqual(banking.debt(c,w.sa),0)
            self.assertFalse(banking.investments(c,w.sa))
            for key in ('food','water','scrap','metal','electronics'):self.assertEqual(read_state(c)['resources'][key],before[key])
            kinds=[json.loads(r[0])['asset_type'] for r in c.execute("SELECT event_data FROM game_events WHERE event_type='bank_liquidation_sale' ORDER BY event_id")]
            self.assertEqual(kinds,['drone'])

    def test_loan_reaches_cap_and_liquidates_without_citizen_loss(self):
        w=self.w;c=self.connection()
        with c,account_scope(w.a):
            state=read_state(c);lid=banking.borrow(c,state,100,1000)
            c.execute('UPDATE bank_loans SET outstanding_balance=199 WHERE loan_id=?',(lid,))
            banking.accrue(c,read_state(c),86400)
            self.assertEqual(banking.debt(c,w.sa),200)
            banking.liquidate(c,read_state(c),86400)
            self.assertEqual(banking.debt(c,w.sa),0)
            self.assertEqual(len(read_state(c)['citizens']),6)
            self.assertEqual(read_state(c)['buildings'][0]['building_type'],'town_hall')

    def test_liquidation_sells_resources_and_leaves_town_hall(self):
        w=self.w;c=self.connection()
        with c,account_scope(w.a):
            state=read_state(c);lid=banking.borrow(c,state,100,1000)
            c.execute("UPDATE bank_loans SET outstanding_balance=200,status='liquidating' WHERE loan_id=?",(lid,))
            c.execute('UPDATE settlement_resources SET credits=0 WHERE settlement_id=?',(w.sa,))
            banking.liquidate(c,read_state(c),86400)
            self.assertTrue(c.execute("SELECT 1 FROM game_events WHERE event_type='bank_liquidation_sale'").fetchone())
            self.assertEqual(read_state(c)['buildings'][0]['status'],'active')
            self.assertEqual(len(read_state(c)['citizens']),6)

    def test_population_and_credit_raid_resolve_end_to_end(self):
        w=self.w;w.weak_defense();aid,ids=w.launch(count=2,objective='credits',level=10)
        w.advance(w.a,8200)
        report=w.reports()[0]
        self.assertEqual(report['result'],'attacker_win')
        self.assertEqual(report['credits_taken'],100)
        self.assertEqual(report['loot']['taken'],{})
        before=w.state(w.a);w.advance(w.a,8200);self.assertEqual(before,w.state(w.a))

    def test_capture_integrates_once_at_midnight_and_not_before(self):
        w=self.w;c=self.connection()
        with c,account_scope(w.a):
            cid=w.state(w.a)['citizens'][-1]['citizen_id']
            c.execute('UPDATE citizens SET integrated=0,morale=100 WHERE citizen_id=?',(cid,))
            self.assertFalse(capture.daily(c,read_state(c),86399))
            self.assertTrue(capture.daily(c,read_state(c),86400))
            self.assertEqual(c.execute('SELECT integrated FROM citizens WHERE citizen_id=?',(cid,)).fetchone()[0],1)
            self.assertFalse(capture.daily(c,read_state(c),86400))

    def test_captured_desertion_can_reduce_population_below_six(self):
        w=self.w;c=self.connection()
        with c,account_scope(w.a):
            cid=read_state(c)['citizens'][-1]['citizen_id']
            c.execute('UPDATE citizens SET integrated=0,morale=0 WHERE citizen_id=?',(cid,))
            with patch('game.capture.random.Random') as rng:
                rng.return_value.random.return_value=0
                self.assertTrue(capture.daily(c,read_state(c),86400))
            self.assertEqual(len(read_state(c)['citizens']),5)
            combat.daily(c,read_state(c),86400)
            self.assertEqual(len(read_state(c)['citizens']),6)

    def test_paused_capture_waits_for_next_active_midnight(self):
        w=self.w;c=self.connection()
        with c,account_scope(w.a):
            cid=read_state(c)['citizens'][-1]['citizen_id']
            c.execute('UPDATE citizens SET integrated=0,morale=100 WHERE citizen_id=?',(cid,))
            from game.recovery import shift_clock
            shift_clock(c,read_state(c),90000,91000)
            self.assertFalse(capture.daily(c,read_state(c),91000))
            self.assertTrue(capture.daily(c,read_state(c),172800))

    def test_midnight_bank_interest_precedes_attack_floor(self):
        w=self.w;c=self.connection()
        with c,account_scope(w.a):
            banking.borrow(c,read_state(c),100,1000)
        w.advance(w.a,86400)
        rows=w.sql("SELECT event_type FROM game_events WHERE settlement_id=? AND occurred_at=86400 AND event_type IN ('bank_interest','combat_daily_rollover') ORDER BY event_id",(w.sa,))
        self.assertEqual(rows,[('bank_interest',),('combat_daily_rollover',)])

    def test_bank_action_settles_offline_players_maturing_investment(self):
        w=self.w;c=self.connection()
        with c,account_scope(w.b):
            iid=banking.invest(c,read_state(c),200,3,1000)
            # Controlled near-term maturity avoids days of unrelated simulation.
            c.execute('UPDATE bank_investments SET matures_at=1100 WHERE investment_id=?',(iid,))
        with account_scope(w.a):expansion.transact(w.path,'borrow',1100,amount=100)
        self.assertEqual(w.sql('SELECT status FROM bank_investments WHERE investment_id=?',(iid,))[0][0],'matured')
        self.assertEqual(w.state(w.b)['resources']['credits'],500)

    def test_final_bank_settlement_returns_investment_and_keeps_unpaid_debt(self):
        w=self.w;c=self.connection()
        with c,account_scope(w.a):
            banking.borrow(c,read_state(c),100,1000)
            banking.invest(c,read_state(c),100,14,1000)
            banking.accrue(c,read_state(c),87400)
            c.execute('UPDATE settlement_resources SET credits=0 WHERE settlement_id=?',(w.sa,))
            banking.finish(c,read_state(c),87400)
            self.assertFalse(banking.investments(c,w.sa))
            # 100 principal + 1 earned repays 101 of the 102 debt.
            self.assertEqual(banking.debt(c,w.sa),1)
            self.assertEqual(banking.loans(c,w.sa)[0]['status'],'settled')

    def test_midnight_capture_precedes_finance_and_is_idempotent(self):
        w=self.w;c=self.connection()
        with c,account_scope(w.a):
            state=read_state(c);cid=state['citizens'][-1]['citizen_id']
            c.execute('UPDATE citizens SET integrated=0,morale=100 WHERE citizen_id=?',(cid,))
            banking.borrow(c,read_state(c),100,1000)
            expansion.boundary(c,read_state(c),86400)
            events=[r[0] for r in c.execute("SELECT event_type FROM game_events WHERE settlement_id=? AND occurred_at=86400 AND event_type IN ('captured_citizen_integrated','bank_interest') ORDER BY event_id",(w.sa,))]
            self.assertEqual(events,['captured_citizen_integrated','bank_interest'])
            self.assertEqual(c.execute('SELECT integrated FROM citizens WHERE citizen_id=?',(cid,)).fetchone()[0],1)
            debt=banking.debt(c,w.sa)
            expansion.boundary(c,read_state(c),86400)
            self.assertEqual(banking.debt(c,w.sa),debt)
            self.assertEqual(c.execute("SELECT count(*) FROM game_events WHERE settlement_id=? AND occurred_at=86400 AND event_type IN ('captured_citizen_integrated','bank_interest')",(w.sa,)).fetchone()[0],2)

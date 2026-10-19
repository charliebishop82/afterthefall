"""Lean standings must exactly match the original saved full-state calculation."""
from contextlib import closing
import json
import sqlite3
import unittest
from unittest.mock import patch

from database.create_database import connect_database
from game import banking,expansion_views,scoring
from game.scoring_reader import saved_scores
from game.settlement import account_scope,read_state
from game.read_queries import read_connection
from tests.fixtures import baseline_world
from tests.test_refresh_reuse import expanded_world


def full_scores(c,state):
    players=[]
    rows=c.execute('SELECT account_id FROM settlements WHERE season_id=? ORDER BY settlement_id',(state['season']['season_id'],)).fetchall()
    for row in rows:
        with account_scope(row[0]):
            current=read_state(c);sid=current['settlement']['settlement_id']
            result=scoring.totals(current,banking.loans(c,sid),banking.investments(c,sid))
            players.append(dict(result,settlement_id=sid,name=current['settlement']['settlement_name'],processed_at=current['settlement']['simulation_processed_at']))
    return scoring.rank(players)


class ScoringReaderTests(unittest.TestCase):
    def setUp(self):self.w=baseline_world(self,'scoring-reader',expanded_world)

    def compare(self):
        w=self.w;state=w.state();before=w.path.read_bytes();queries=[]
        with read_connection(w.path,rows=True) as c:
            c.set_trace_callback(queries.append)
            expected=full_scores(c,state);old_count=len(queries);queries.clear()
            with patch('game.expansion_views.read_state',side_effect=AssertionError('Full state loading is forbidden')):
                actual=expansion_views.scores(c,state)
            self.assertEqual(actual,expected)
            self.assertLess(len(queries),old_count)
            self.assertFalse(any('citizen_assignments' in sql or 'prototype_recovery_clock' in sql or 'waste_expeditions' in sql for sql in queries))
            self.assertIs(c.row_factory,sqlite3.Row)
            self.assertTrue(c.in_transaction)
        self.assertEqual(w.path.read_bytes(),before)
        return actual

    def job(self,bid,kind,status,spent,done=60,required=120):
        w=self.w
        return w.sql("INSERT INTO settlement_jobs(settlement_id,job_type,target_type,target_building_id,work_required,work_completed,status,created_at,started_at,last_processed_at,inputs_spent) VALUES (?,?,'building',?,?,?,?,1000,1000,1000,?) RETURNING job_id",(w.sa,kind,bid,required,done,status,json.dumps(spent)))[0][0]

    def test_saved_standings_ties_and_order_are_identical(self):
        rows=self.compare()
        self.assertEqual([r['settlement_id'] for r in rows],[self.w.sa,self.w.sb])
        self.assertEqual([r['rank'] for r in rows],[1,1])

    def test_construction_upgrade_damage_and_ignored_jobs_are_identical(self):
        w=self.w;bid=w.build('garden')
        w.sql("UPDATE buildings SET status='construction',current_hp=15 WHERE building_id=?",(bid,))
        self.job(bid,'construction','active',dict(scrap=33,metal=7,electronics=2,_damage=10))
        upgrade=w.build('greenhouse')
        w.sql("UPDATE buildings SET status='upgrading',current_hp=25 WHERE building_id=?",(upgrade,))
        self.job(upgrade,'construction','completed',dict(scrap=41,metal=3,electronics=1),done=120)
        self.job(upgrade,'upgrade','paused',dict(scrap=77,metal=9,electronics=4))
        self.job(upgrade,'upgrade','cancelled',dict(scrap=99999))
        self.job(upgrade,'repair','completed',dict(scrap=99999),done=120)
        ruined=w.build('garden',x=25,y=25)
        w.sql("UPDATE buildings SET status='ruined',current_hp=0 WHERE building_id=?",(ruined,))
        self.compare()

    def test_debt_investment_living_and_zero_hp_filters_are_identical(self):
        w=self.w;season=w.state()['season']['season_id']
        for status,amount in [('active',100),('liquidating',50),('settled',30),('settled',0),('repaid',999)]:
            w.sql('INSERT INTO bank_loans(season_id,settlement_id,original_principal,outstanding_balance,daily_rate,opened_at,interest_processed_at,status) VALUES (?,?,100,?,0,1000,1000,?)',(season,w.sa,amount,status))
        for status in ('active','withdrawn','matured','settled'):
            w.sql("INSERT INTO bank_investments(season_id,settlement_id,principal,daily_rate,accrued_interest,opened_at,matures_at,interest_processed_at,status,terms_data) VALUES (?,?,75,0,4,1000,2000,1000,?,'{}')",(season,w.sa,status))
        ids=[c['citizen_id'] for c in w.state()['citizens']]
        w.sql('UPDATE citizens SET level=3,current_hp=.1,morale=0 WHERE citizen_id=?',(ids[0],))
        w.sql('UPDATE citizens SET current_hp=0 WHERE citizen_id=?',(ids[1],))
        w.sql("UPDATE citizens SET status='dead',current_hp=0 WHERE citizen_id=?",(ids[2],))
        self.compare()

    def test_deployed_damaged_destroyed_units_and_committed_ammunition_are_identical(self):
        w=self.w;one=w.unit('offensive_drone',hp=50);two=w.unit('offensive_drone');three=w.unit('offensive_drone')
        w.sql("UPDATE military_units SET status='deployed' WHERE unit_id=?",(two,))
        w.sql("UPDATE military_units SET status='destroyed',current_hp=0 WHERE unit_id=?",(three,))
        state=w.state();season=state['season']['season_id']
        home=w.build(state['config']['units']['missile']['storage'])
        inv=w.sql("INSERT INTO military_inventory(settlement_id,building_id,unit_type,quantity,updated_at) VALUES (?,?,'missile',2,1000) RETURNING inventory_id",(w.sa,home))[0][0]
        attack=w.sql("INSERT INTO attacks(season_id,attacker_settlement_id,defender_settlement_id,launched_at,resolves_at,status,raid_objective,random_seed) VALUES (?,?,?,1000,2000,'in_flight','scrap','scoring-reader') RETURNING attack_id",(season,w.sa,w.sb))[0][0]
        w.sql("INSERT INTO attack_munitions(attack_id,inventory_id,participant_settlement_id,role,quantity,consumed_quantity) VALUES (?,?,?,'attacker',3,1)",(attack,inv,w.sa))
        before=self.compare()
        w.sql("UPDATE attacks SET status='resolved',resolved_at=2000 WHERE attack_id=?",(attack,))
        after=self.compare()
        self.assertGreater(next(r['military'] for r in before if r['settlement_id']==w.sa),next(r['military'] for r in after if r['settlement_id']==w.sa))

    def test_later_calls_are_fresh_and_empty_season_needs_no_state_reads(self):
        w=self.w;first=self.compare()
        w.sql('UPDATE settlement_resources SET credits=credits+1000 WHERE settlement_id=?',(w.sb,))
        second=self.compare();self.assertNotEqual(first,second)
        with read_connection(w.path) as c:
            self.assertEqual(saved_scores(c,999999),[])
            self.assertEqual(c.execute('SELECT 1').fetchone(),(1,))

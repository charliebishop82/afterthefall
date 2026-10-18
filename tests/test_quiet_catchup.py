"""Compare conservative bulk catch-up with the original minute path."""
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import sqlite3
import json
import unittest
from unittest.mock import patch

from database.create_database import connect_database
from game import economy, quiet
from game.calculations import scope
from game.settlement import account_scope
from game.simulation import advance_settlement
from tests.fixtures import SupportWorld, fixed_map_seed


class QuietTests(unittest.TestCase):
    def world(self):
        with fixed_map_seed():w=SupportWorld(self)
        w.change('enable_consequences')
        garden=w.build('garden',x=21,y=18)
        rain=w.build('rain_collector',x=23,y=18)
        w.staff(garden,count=2)  # Rain Collectors are passive.
        for c in w.state()['citizens']:
            if c['assignment']=='unassigned':
                w.sql("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,assigned_at) VALUES (?,?,'patrol',1000)",
                      (c['citizen_id'],w.sa))
        w.sql('UPDATE citizens SET unemployed_since=NULL WHERE settlement_id=?',(w.sa,))
        capacity=economy.storage(w.state())
        w.sql('UPDATE settlement_resources SET food=?,water=? WHERE settlement_id=?',
              (capacity['food'],capacity['water'],w.sa))
        return w

    def test_bulk_matches_detailed_totals_xp_and_partial_minute(self):
        w=self.world();self.assertTrue(quiet.eligible(w.state()))
        copy=Path(w.tmp.name)/'detailed.db'
        with closing(connect_database(w.path)) as source,closing(sqlite3.connect(copy)) as target:
            source.backup(target)
        with account_scope(w.a),patch('game.quiet.eligible',return_value=False),scope() as detailed:
            expected=advance_settlement(copy,4607)
        with account_scope(w.a),scope() as bulk:
            actual=advance_settlement(w.path,4607)
        self.assertLess(bulk['simulation_intervals'],detailed['simulation_intervals'])
        self.assertEqual(actual['settlement']['simulation_processed_at'],4607)
        for r in ('food','water','scrap','metal','electronics','credits'):
            self.assertAlmostEqual(actual['resources'][r],expected['resources'][r],places=7)
        for a,b in zip(actual['citizens'],expected['citizens']):
            for key in ('level','morale','current_hp','assignment'):
                self.assertEqual(a[key],b[key],key)
            self.assertAlmostEqual(a['xp'],b['xp'],places=7)
        self.assertEqual(set(actual['xp_clock']['pending']),set(expected['xp_clock']['pending']))
        for cid,value in actual['xp_clock']['pending'].items():
            self.assertAlmostEqual(value,expected['xp_clock']['pending'][cid],places=7)

    def test_health_pending_work_shortages_and_different_housing_disable_bulk(self):
        w=self.world();original=w.state();self.assertTrue(quiet.eligible(original))
        variants=[]
        state=deepcopy(original);state['citizens'][0]['current_hp']-=1;variants.append(state)
        state=deepcopy(original);state['resources']['food']=0;variants.append(state)
        state=deepcopy(original);state['xp_clock']['pending']={'1':0.1};variants.append(state)
        state=deepcopy(original);state['jobs'].append({'status':'active'});variants.append(state)
        state=deepcopy(original);state['citizens'][0]['homeless_since']=1000;variants.append(state)
        state=deepcopy(original);state['reserved']={'food':1};variants.append(state)
        state=deepcopy(original)
        cid=state['citizens'][0]['citizen_id']
        state['recovery_housing']['assignments'][cid]=dict(state['recovery_housing']['assignments'][cid],quality=99)
        variants.append(state)
        for index,state in enumerate(variants):
            self.assertFalse(quiet.eligible(state),index)

    def compare_detailed(self,w,until=4607):
        copy=Path(w.tmp.name)/'detailed-stock.db'
        with closing(connect_database(w.path)) as source,closing(sqlite3.connect(copy)) as target:
            source.backup(target)
        with account_scope(w.a),patch('game.quiet.eligible',return_value=False),scope() as detailed:
            expected=advance_settlement(copy,until)
        with account_scope(w.a),scope() as bulk:
            actual=advance_settlement(w.path,until)
        self.assertLess(bulk['simulation_intervals'],detailed['simulation_intervals'])
        for r in ('food','water','scrap','metal','electronics','credits'):
            self.assertAlmostEqual(actual['resources'][r],expected['resources'][r],places=7)
        for a,b in zip(actual['citizens'],expected['citizens']):
            for key in ('level','current_hp','xp','morale'):
                self.assertAlmostEqual(a[key],b[key],places=7,msg=key)
        self.assertEqual(set(actual['xp_clock']['pending']),set(expected['xp_clock']['pending']))
        for cid,value in actual['xp_clock']['pending'].items():
            self.assertAlmostEqual(value,expected['xp_clock']['pending'][cid],places=7)

    def test_growing_stock_and_transition_minute_match_detailed_simulation(self):
        w=self.world()
        w.sql('UPDATE settlement_resources SET food=food-2 WHERE settlement_id=?',(w.sa,))
        self.assertTrue(quiet.eligible(w.state()))
        self.compare_detailed(w)

    def test_draining_stock_stops_bulk_before_depletion(self):
        w=self.world()
        garden=next(b for b in w.state()['buildings'] if b['building_type']=='garden')
        w.sql('UPDATE citizen_assignments SET ended_at=1000 WHERE building_id=? AND ended_at IS NULL',(garden['building_id'],))
        w.sql('UPDATE settlement_resources SET food=2 WHERE settlement_id=?',(w.sa,))
        self.assertTrue(quiet.eligible(w.state()))
        self.compare_detailed(w)

    def test_idle_morale_loss_is_linear_without_changing_worker_production(self):
        w=self.world()
        w.sql("UPDATE citizen_assignments SET ended_at=1000 WHERE settlement_id=? AND assignment_type='patrol' AND ended_at IS NULL",(w.sa,))
        ids=[c['citizen_id'] for c in w.state()['citizens'] if c['assignment']=='unassigned']
        self.assertTrue(ids)
        for cid in ids:w.sql('UPDATE citizens SET unemployed_since=-50000 WHERE citizen_id=?',(cid,))
        from game.consequences import record
        from game.settlement import read_state
        with closing(connect_database(w.path)) as c,c,account_scope(w.a):
            c.row_factory=sqlite3.Row
            state=read_state(c);clock=deepcopy(state['consequences_clock']);clock['enabled_at']=-50000
            record(c,state,1000,clock)
        self.assertTrue(quiet.eligible(w.state()))
        self.compare_detailed(w)

    def test_xp_level_boundary_remains_on_original_minute_grid(self):
        w=self.world();state=w.state();citizen=state['citizens'][0]
        citizen['xp']=99.01
        with patch('game.progression.hourly_rates',return_value={citizen['citizen_id']:10}):
            self.assertEqual(quiet.xp_boundary(state),1360)

    def test_material_converters_keep_detailed_processing(self):
        w=self.world()
        w.build('recycler',x=21,y=22)
        self.assertFalse(quiet.eligible(w.state()))

    def test_shared_material_fill_is_a_boundary_even_with_food_and_water_full(self):
        w=self.world();state=w.state();flow=economy.rates(state)
        flow['scrap']['net']=10
        flow['scrap']['capacity']=sum(state['resources'][r] for r in ('scrap','metal','electronics'))+2
        self.assertEqual(quiet.stock_boundary(state,flow),1720)


    def test_unstaffed_paused_scavenging_matches_detail_without_work_loot_or_survivor_gains(self):
        w=self.world();state=w.state();season=state['season']['season_id']
        kind=next(iter(state['config']['derelicts']))
        common=w.sql('INSERT INTO season_derelicts(season_id,derelict_type,origin_x,origin_y) VALUES (?,?,0,0) RETURNING season_derelict_id',(season,kind))[0][0]
        loot=dict.fromkeys(('food','water','scrap','metal','electronics'),20)
        recovered=dict.fromkeys(loot,1)
        did=w.sql("INSERT INTO settlement_derelicts(settlement_id,season_id,season_derelict_id,status,random_key_ref,random_nonce,random_result,recovered_loot,created_at) VALUES (?,?,?,'scavenging','fixture','fixture',?,?,1000) RETURNING settlement_derelict_id",
                  (w.sa,season,common,json.dumps(loot),json.dumps(recovered)))[0][0]
        jid=w.sql("INSERT INTO settlement_jobs(settlement_id,job_type,target_type,target_derelict_id,work_required,work_completed,status,created_at,started_at,last_processed_at,pause_reason) VALUES (?,'scavenging','derelict',?,7200,100,'paused',1000,1000,1000,'No safe effective scavengers') RETURNING job_id",(w.sa,did))[0][0]
        before=w.state()
        self.assertTrue(quiet.eligible(before))
        self.compare_detailed(w)
        after=w.state()
        job=next(job for job in after['jobs'] if job['job_id']==jid)
        derelict=next(d for d in after['derelicts'] if d['settlement_derelict_id']==did)
        self.assertEqual(job['work_completed'],100)
        self.assertEqual(job['status'],'paused')
        self.assertEqual(json.loads(derelict['recovered_loot']),recovered)
        self.assertEqual(len(after['citizens']),len(before['citizens']))

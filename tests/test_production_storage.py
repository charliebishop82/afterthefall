"""Useful work, input conservation, and XP at storage boundaries."""
from contextlib import closing
import copy
import random
import sqlite3
import unittest

from game.economy import rates, storage, advance_resources
from game.progression import hourly_rates, accrue
from game.production_flow import material_flow
from game.settlement import account_scope
from game.simulation import advance_settlement
from database.create_database import connect_database
from tests.fixtures import SupportWorld


class MaterialStorageTests(unittest.TestCase):
    def flow(self, scrap=100, electronics=0, incoming=0, reserved=0, seconds=None):
        state={'resources':{'scrap':scrap,'metal':0,'electronics':electronics},'reserved':{'scrap':reserved}}
        utility={'buildings':{1:{'inputs':{'scrap':10},'outputs':{'metal':4},'reason':''}}}
        loot={'scrap':incoming,'metal':0,'electronics':0}
        material_flow(state,utility,loot,100,seconds)
        return utility['buildings'][1],loot

    def test_lossy_conversion_runs_in_full_shared_pool(self):
        status,loot=self.flow()
        self.assertEqual(status['inputs']['scrap'],10)
        self.assertEqual(status['outputs']['metal'],4)
        self.assertEqual(status['work_fraction'],1)

    def test_overflow_salvage_is_discarded_before_converter_output(self):
        status,loot=self.flow(incoming=20)
        self.assertAlmostEqual(loot['scrap'],6,places=8)
        self.assertEqual(status['outputs']['metal'],4)
        self.assertEqual(status['inputs']['scrap'],10)
        self.assertLessEqual(loot['scrap']+status['outputs']['metal']-status['inputs']['scrap'],1e-8)

    def test_arriving_inputs_cannot_create_unstorable_output(self):
        status,loot=self.flow(scrap=0,electronics=100,incoming=10)
        self.assertEqual(status['work_fraction'],0)
        self.assertEqual(status['inputs']['scrap'],0)
        self.assertEqual(status['outputs']['metal'],0)
        self.assertEqual(loot['scrap'],0)

    def test_reserved_inputs_are_not_spent(self):
        status,_=self.flow(reserved=100)
        self.assertEqual(status['work_fraction'],0)
        self.assertEqual(status['inputs']['scrap'],0)

    def test_partial_interval_uses_only_available_inputs(self):
        status,_=self.flow(scrap=.05,seconds=60)
        self.assertAlmostEqual(status['work_fraction'],.3)
        self.assertAlmostEqual(status['inputs']['scrap']/60,.05)
        self.assertAlmostEqual(status['outputs']['metal']/60,.02)

    def test_two_converters_cannot_spend_the_same_remaining_input(self):
        state={'resources':{'scrap':.1,'metal':0,'electronics':0}}
        utility={'buildings':{bid:{'inputs':{'scrap':10},'outputs':{'metal':4},'reason':''} for bid in (1,2)}}
        loot={'scrap':0,'metal':0,'electronics':0}
        material_flow(state,utility,loot,100,60)
        self.assertAlmostEqual(sum(s['inputs']['scrap'] for s in utility['buildings'].values())/60,.1)
        self.assertAlmostEqual(sum(s['outputs']['metal'] for s in utility['buildings'].values())/60,.04)

    def test_downstream_fabricators_free_space_before_surplus_salvage_is_kept(self):
        state={'resources':{'scrap':0,'metal':100,'electronics':0}}
        utility={'buildings':{
            1:{'inputs':{'scrap':10},'outputs':{'metal':7},'reason':''},
            2:{'inputs':{'scrap':6,'metal':6},'outputs':{'electronics':2},'reason':''},
            3:{'inputs':{'scrap':6,'metal':6},'outputs':{'electronics':2},'reason':''}}}
        loot={'scrap':24,'metal':0,'electronics':0}
        material_flow(state,utility,loot,100,None)
        self.assertAlmostEqual(loot['scrap'],23)
        self.assertEqual([s['work_fraction'] for s in utility['buildings'].values()],[1,1,1])
        self.assertEqual(utility['buildings'][1]['outputs']['metal'],7)
        self.assertEqual(sum(s['outputs'].get('electronics',0) for s in utility['buildings'].values()),4)

    def test_seeded_converter_combinations_preserve_capacity_and_reservations(self):
        rng=random.Random(4811)
        for case in range(2000):
            parts=[rng.random() for _ in range(3)];total=sum(parts)
            stocks={r:100*v/total for r,v in zip(('scrap','metal','electronics'),parts)}
            if case%3==0:
                stocks={'scrap':0,'metal':100 if case%2 else 0,'electronics':0 if case%2 else 100}
            reserved={r:v*rng.random() for r,v in stocks.items()}
            state={'resources':stocks,'reserved':reserved};utility={'buildings':{}}
            for bid in range(1,rng.randrange(2,7)):
                factor=rng.uniform(.1,3)
                inputs={'scrap':10*factor} if bid%2 else {'scrap':6*factor,'metal':6*factor}
                outputs={'metal':7*factor} if bid%2 else {'electronics':2*factor}
                utility['buildings'][bid]={'inputs':inputs,'outputs':outputs,'reason':''}
            loot={r:rng.uniform(0,40) for r in stocks};seconds=rng.choice((1,60,3600))
            material_flow(state,utility,loot,100,seconds)
            ends={r:stocks[r]+seconds/3600*(loot[r]+sum(s['outputs'].get(r,0)-s['inputs'].get(r,0)
                  for s in utility['buildings'].values())) for r in stocks}
            with self.subTest(case=case):
                self.assertLessEqual(sum(ends.values()),100+1e-7)
                for resource in stocks:
                    self.assertGreaterEqual(ends[resource],reserved[resource]-1e-7)


class SupplyStorageTests(unittest.TestCase):
    def setUp(self):
        self.w=SupportWorld(self)
        self.w.change('enable_consequences')
        self.garden=self.w.build('garden')
        self.worker=self.w.staff(self.garden)[0]
        store=storage(self.w.state())
        self.w.sql('UPDATE settlement_resources SET food=?,water=? WHERE settlement_id=?',
                   (store['food'],store['water'],self.w.sa))

    def test_full_food_pool_replaces_consumption_and_scales_work_xp(self):
        w=self.w;state=w.state();flow=rates(state)
        self.assertEqual(flow['food']['production'],flow['food']['consumption'])
        self.assertEqual(flow['food']['net'],0)
        earned=hourly_rates(state)[self.worker]
        self.assertGreater(earned,0)
        self.assertLess(earned,1)
        after=w.advance(1060)
        self.assertAlmostEqual(after['resources']['food'],state['resources']['food'])
        worker=next(c for c in after['citizens'] if c['citizen_id']==self.worker)
        self.assertAlmostEqual(worker['xp'],earned/60)

    def test_fully_stalled_output_awards_no_production_xp(self):
        state=copy.deepcopy(self.w.state())
        for resource in ('food','water'):
            state['config']['simulation'][resource+'_per_citizen_per_hour']=0
        self.assertEqual(rates(state)['food']['production'],0)
        self.assertNotIn(self.worker,hourly_rates(state))
        admin=next(c['citizen_id'] for c in state['citizens'] if c['assignment']=='administrator')
        self.assertNotIn(admin,hourly_rates(state))

    def test_nearly_full_output_awards_only_the_work_that_fits(self):
        w=self.w;state=copy.deepcopy(w.state())
        for resource in ('food','water'):
            state['config']['simulation'][resource+'_per_citizen_per_hour']=0
        state['resources']['food']-=.05
        with closing(connect_database(w.path)) as c,c,account_scope(w.a):
            amounts=advance_resources(c,state,60,1060)
            accrue(c,state,60,1060)
            self.assertAlmostEqual(amounts['food'],state['resources']['food']+.05)
            xp=c.execute('SELECT xp FROM citizens WHERE citizen_id=?',(self.worker,)).fetchone()[0]
            self.assertGreater(xp,0)
            self.assertLess(xp,1/60)

    def test_full_storage_offline_and_small_requests_agree(self):
        w=self.w;other=w.path.with_name('offline.db')
        with closing(sqlite3.connect(w.path)) as a,closing(sqlite3.connect(other)) as b:
            a.backup(b)
        for now in (1003,1023,1059,1060,1101,1179,1244,1300):
            w.advance(now)
        with account_scope(w.a):
            offline=advance_settlement(other,1300)
        many=w.state()
        for resource in ('food','water','scrap','metal','electronics'):
            self.assertAlmostEqual(many['resources'][resource],offline['resources'][resource])
        for one,two in zip(many['citizens'],offline['citizens']):
            self.assertAlmostEqual(one['xp'],two['xp'])
            self.assertEqual(one['level'],two['level'])

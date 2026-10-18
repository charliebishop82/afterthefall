"""Performance changes must preserve utility, coverage and simulation outcomes."""
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import json
import sqlite3
import unittest
from unittest.mock import patch

from database.create_database import connect_database
from game import economy
from game import catchup
from game.buildings import footprint
from game.calculations import scope, CURRENT
from game.production_flow import input_retry
from game.settlement import account_scope
from game.simulation import advance_settlement
from tests.fixtures import SupportWorld, CombatWorld, fixed_map_seed


class CalculationTests(unittest.TestCase):
    def world(self):
        with fixed_map_seed():
            return SupportWorld(self)

    def test_cached_allocations_are_independent_and_state_is_untouched(self):
        w=self.world();state=w.state();before=deepcopy(state)
        expected=economy.utilities(state)
        with scope() as metrics:
            economy.utilities(state)  # Prime the immutable cached template.
            first=economy.utilities(state)
            first['capacity']['oxygen']=-999
            first['zones']['oxygen'][0]['current_hp']=0
            first['buildings'].clear()
            second=economy.utilities(state)
            self.assertEqual(second,expected)
            self.assertEqual(metrics['utility_hits'],2)
        self.assertEqual(state,before)

    def test_production_throttling_does_not_poison_cached_outputs(self):
        w=self.world();state=w.state();before=deepcopy(state)
        expected=economy.utilities(state)
        with scope() as metrics:
            allocation=economy.utilities(state)
            economy.rates(state,allocation,seconds=60)
            self.assertEqual(economy.utilities(state),expected)
            self.assertGreater(metrics['utility_hits'],0)
        self.assertEqual(state,before)

    def test_health_morale_staffing_geometry_and_absence_invalidate_allocation(self):
        w=self.world();state=w.state()
        with scope() as metrics:
            economy.utilities(state)
            mutations=[(state['citizens'][0],'current_hp',50),
                       (state['citizens'][0],'effective_morale',20),
                       (state['citizens'][0],'assignment','patrol' if state['citizens'][0]['assignment']=='unassigned' else 'unassigned'),
                       (state['citizens'][0],'away',True),
                       (state['buildings'][1],'origin_x',0),
                       (state['buildings'][1],'current_hp',0)]
            for entity,key,value in mutations:
                entity[key]=value
                actual=economy.utilities(state)
                self.assertEqual(actual,economy.utilities.__wrapped__(state),key)
            self.assertEqual(metrics['utility_hits'],0)

    def test_geometry_cache_matches_original_tile_algorithm_and_tracks_provider_changes(self):
        w=self.world();state=w.state();b=state['buildings'][1]
        zones=[state['buildings'][0]]
        for x,y,rotation in ((21,15,0),(0,0,90),(17,18,180),(35,35,270)):
            b.update(origin_x=x,origin_y=y,rotation=rotation)
            width,height=footprint(state,b)
            expected=sum(any(economy.within_zone(state,tx,ty,z) for z in zones)
                         for tx in range(x,x+width) for ty in range(y,y+height))/(width*height)
            self.assertEqual(economy.zone_fraction(state,b,zones),expected)
        zones[0]['origin_x']=0
        self.assertEqual(economy.zone_fraction(state,b,[]),0)
        width,height=footprint(state,b)
        expected=sum(economy.within_zone(state,x,y,zones[0])
                     for x in range(b['origin_x'],b['origin_x']+width)
                     for y in range(b['origin_y'],b['origin_y']+height))/(width*height)
        self.assertEqual(economy.zone_fraction(state,b,zones),expected)

    def test_operation_cache_is_discarded_even_after_exception(self):
        with self.assertRaisesRegex(ValueError,'fixture'):
            with scope():
                raise ValueError('fixture')
        self.assertIsNone(CURRENT.get())

    def test_scavenging_reuses_crew_speed_without_losing_any_resource_yield(self):
        w=self.world();state=w.state()
        for resource in ('food','water','scrap','metal','electronics'):
            state['resources'][resource]=0
        baseline=economy.rates(state)
        state['derelicts'].append({'settlement_derelict_id':777,
            'random_result':json.dumps(dict.fromkeys(('food','water','scrap','metal','electronics'),1))})
        state['jobs'].append({'job_type':'scavenging','status':'active',
                             'target_derelict_id':777,'work_required':3600})
        with patch('game.scavenging.speed',return_value=1) as speed, \
             patch('game.support.best',return_value=0):
            actual=economy.rates(state)
        self.assertEqual(speed.call_count,1)
        for resource in ('food','water','scrap','metal','electronics'):
            self.assertAlmostEqual(actual[resource]['production']-baseline[resource]['production'],1)

    def test_cached_and_uncached_simulations_have_same_saved_outcomes(self):
        w=self.world()
        copy=Path(w.tmp.name)/'uncached.db'
        with closing(connect_database(w.path)) as source, closing(sqlite3.connect(copy)) as target:
            source.backup(target)
        with patch('game.economy.utilities',economy.utilities.__wrapped__), account_scope(w.a):
            expected=advance_settlement(copy,2200)
        with account_scope(w.a),scope() as metrics:
            actual=advance_settlement(w.path,2200)
            self.assertGreater(metrics['utility_hits'],0)
        for key in ('resources','citizens','buildings','jobs','xp_clock','needs_clock','recovery_clock','regen_pending'):
            self.assertEqual(actual[key],expected[key],key)

    def test_quiet_horizon_can_cover_more_time_but_season_end_stays_bounded(self):
        w=self.world();targets=[]
        def advance(c,state,now,**kwargs):
            targets.append(now)
            c.execute('UPDATE settlements SET simulation_processed_at=? WHERE settlement_id=?',
                      (now,state['settlement']['settlement_id']))
        with patch('game.simulation._advance',side_effect=advance):
            catchup.step(w.path,w.a,10000)
        self.assertEqual(targets,[1000+catchup.HORIZON])
        # A distant finalization must not pull every player through an hour of
        # dependencies in one atomic finalization operation.
        w.sql('UPDATE settlements SET simulation_processed_at=1000')
        w.sql('UPDATE seasons SET finalization_at=2000,ends_at=2500')
        targets.clear()
        with patch('game.simulation._advance',side_effect=advance):
            catchup.step(w.path,w.a,3000)
        self.assertEqual(targets,[2200])

    def test_due_combat_does_not_inherit_the_full_quiet_horizon(self):
        with fixed_map_seed():w=CombatWorld(self)
        w.launch()
        before=w.state(w.a)['settlement']['simulation_processed_at']
        w.sql('UPDATE settlements SET simulation_processed_at=?',(before,))
        targets=[]
        def advance(c,state,now,**kwargs):
            targets.append(now)
        with patch('game.simulation._advance',side_effect=advance):
            catchup.step(w.path,w.a,20000)
        self.assertEqual(targets,[before+300])


class InputRetryTests(unittest.TestCase):
    def state(self,kind):
        return {'buildings':[{'building_id':1},{'building_id':2,'building_type':kind,'level':1}],
                'resources':{'scrap':0,'metal':0},'reserved':{},
                'config':{'buildings':{kind:{'levels':[{'scrap_input':2 if kind=='recycler' else 0,
                                                     'metal_input':2 if kind=='electronics_fabricator' else 0}]}}}}

    def test_unrelated_scrap_does_not_retry_metal_starved_fabricator_every_second(self):
        rates={'scrap':{'production':5},'metal':{'production':0}}
        statuses={2:{'reason':'Waiting for input materials'}}
        self.assertFalse(input_retry(self.state('electronics_fabricator'),rates,statuses))

    def test_real_arriving_input_retains_first_second_restart(self):
        rates={'scrap':{'production':5},'metal':{'production':0}}
        statuses={2:{'reason':'Waiting for input materials'}}
        self.assertTrue(input_retry(self.state('recycler'),rates,statuses))
        statuses[2]['reason']='Not enough electricity capacity'
        self.assertFalse(input_retry(self.state('recycler'),rates,statuses))


"""Natural healing, reversible housing morale, and deterministic offline time."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import unittest
from urllib.parse import urlencode

from tests import test_population as population_tests
from tests import test_prototype as prototype_tests
from database.create_database import connect_database
from game.settlement import read_settlement,load_config,prepare_database
from game.buildings import change_building,productivity
from game.population import housing
from game.simulation import apply_action,advance_settlement,resource_rates
from game.recovery import eligibility
from game.views import render_page


class RecoveryTests(unittest.TestCase):
    setUp=population_tests.PopulationTests.setUp
    sql=population_tests.PopulationTests.sql
    state=population_tests.PopulationTests.state
    home=population_tests.PopulationTests.home
    survivor=population_tests.PopulationTests.survivor

    def enable(self):return change_building(self.path,'enable_recovery',now=1000)

    def test_enable_preserves_health_base_morale_and_old_loot(self):
        change_building(self.path,'enable_housing',now=1000)
        self.sql('UPDATE citizens SET current_hp=75,morale=35 WHERE citizen_id=2')
        before=self.state();state=self.enable()
        self.assertEqual(state['resources'],before['resources'])
        self.assertEqual(state['derelicts'],before['derelicts'])
        self.assertEqual([(c['current_hp'],c['morale']) for c in state['citizens']],[(c['current_hp'],c['morale']) for c in before['citizens']])
        self.assertEqual(state,change_building(self.path,'enable_recovery',now=1000))
        self.assertEqual(state,change_building(self.path,'enable_housing',now=1000))
        self.assertEqual(state,change_building(self.path,'enable',now=1000))

    def test_workbook_rates_and_older_configuration_unchanged(self):
        self.assertEqual(load_config('prototype_v6')['recovery']['natural_hp_per_hour'],2)
        self.assertEqual(load_config('prototype_v6')['recovery']['powered_comfort'],1)
        self.assertNotIn('recovery',load_config('prototype_v5'))
        self.assertEqual(load_config('prototype_v5')['buildings'],load_config('prototype_v6')['buildings'])

    def test_two_hp_per_hour_and_level_maximum_cap(self):
        self.enable();self.sql('UPDATE citizens SET current_hp=75 WHERE citizen_id=2')
        self.sql('UPDATE citizens SET level=2,current_hp=107.99 WHERE citizen_id=3')
        apply_action(self.path,'resume',now=1000)
        state=advance_settlement(self.path,now=4600)
        self.assertAlmostEqual(state['citizens'][1]['current_hp'],77,places=8)
        self.assertEqual(state['citizens'][2]['current_hp'],108)
        self.assertEqual(state['citizens'][0]['current_hp'],100)
        self.assertEqual(state['citizens'][1]['max_hp'],100)

    def test_healing_has_no_effect_before_enable(self):
        change_building(self.path,'enable_housing',now=1000)
        self.sql('UPDATE citizens SET current_hp=75 WHERE citizen_id=2')
        apply_action(self.path,'resume',now=1000)
        self.assertEqual(advance_settlement(self.path,now=4600)['citizens'][1]['current_hp'],75)

    def test_paused_and_suspended_time_does_not_heal(self):
        self.enable();self.sql('UPDATE citizens SET current_hp=75 WHERE citizen_id=2')
        self.assertEqual(advance_settlement(self.path,now=10000)['citizens'][1]['current_hp'],75)
        apply_action(self.path,'resume',now=10000)
        state=advance_settlement(self.path,now=10060)
        self.assertAlmostEqual(state['citizens'][1]['current_hp'],75+2/60)
        self.sql("UPDATE settlements SET status='suspended'")
        self.assertEqual(advance_settlement(self.path,now=12000)['citizens'][1]['current_hp'],state['citizens'][1]['current_hp'])

    def test_partial_minute_credit_survives_pause_resume(self):
        self.enable();self.sql('UPDATE citizens SET current_hp=75 WHERE citizen_id=2')
        apply_action(self.path,'resume',now=1000);apply_action(self.path,'pause',now=1010)
        self.assertEqual(self.state()['recovery_clock']['pending']['2'],10)
        apply_action(self.path,'resume',now=2010)
        state=advance_settlement(self.path,now=2060)
        self.assertAlmostEqual(state['citizens'][1]['current_hp'],75+2/60)
        self.assertEqual(state['recovery_clock']['pending'],{})

    def test_unsafe_homeless_and_zero_hp_do_not_recover(self):
        self.enable();self.sql('UPDATE citizens SET current_hp=75 WHERE citizen_id=6')
        self.sql('UPDATE citizens SET current_hp=0 WHERE citizen_id=5')
        self.sql('UPDATE buildings SET current_hp=500 WHERE building_id=1')
        self.assertEqual(eligibility(self.state())[6],'Needs safe housing')
        apply_action(self.path,'resume',now=1000)
        state=advance_settlement(self.path,now=4600)
        self.assertEqual(state['citizens'][5]['current_hp'],75)
        self.assertEqual(state['citizens'][4]['current_hp'],0)

    def test_no_food_or_water_and_inaccessible_food_block_recovery(self):
        self.enable();self.sql('UPDATE citizens SET current_hp=75 WHERE citizen_id=2')
        self.sql('UPDATE settlement_resources SET food=0')
        self.assertEqual(eligibility(self.state())[2],'Needs accessible Food and Water')
        with self.assertRaises(ValueError):apply_action(self.path,'resume',now=1000)
        self.sql('UPDATE settlement_resources SET food=120,water=0')
        self.assertEqual(eligibility(self.state())[2],'Needs accessible Food and Water')
        self.sql('UPDATE settlement_resources SET water=120')
        bid=self.home('cold_storage',x=0,y=0)
        state=self.state()
        from game.economy import storage,available_food
        cap=storage(state)['food']
        self.sql("INSERT INTO game_events(season_id,settlement_id,event_type,occurred_at,event_data) VALUES (1,1,'prototype_food_storage_lock',1000,?)",(json.dumps({'protected_food':120,'capacity':cap,'signature':[[bid,1]]}),))
        self.assertEqual(available_food(self.state()),0)
        self.assertEqual(eligibility(self.state())[2],'Needs accessible Food and Water')
        self.assertEqual(self.state()['citizens'][1]['current_hp'],75)

    def test_tent_penalty_is_reversible_not_accumulated(self):
        self.enable();self.sql('UPDATE buildings SET current_hp=500 WHERE building_id=1')
        bid=self.home('pup_tent')
        state=self.state();c=state['citizens'][5]
        self.assertEqual((c['morale'],c['effective_morale'],c['housing_morale_modifier']),(60,52,-8))
        self.assertEqual(self.state(),state)
        self.sql("UPDATE buildings SET status='demolished' WHERE building_id=?",(bid,))
        self.assertEqual(self.state()['citizens'][5]['effective_morale'],60)
        self.assertEqual(self.sql('SELECT morale FROM citizens WHERE citizen_id=6'),[(60.0,)])

    def test_house_power_comfort_and_loss_keep_capacity(self):
        self.enable();bid=self.home('house',level=2)
        state=self.state()
        self.assertEqual(state['citizens'][0]['effective_morale'],63)
        self.assertEqual(housing(state)['capacity'],15)
        self.home('oxygen_garden',x=23,y=18)
        self.sql('UPDATE buildings SET origin_x=25 WHERE building_id=?',(bid,))
        state=self.state()
        self.assertEqual(state['citizens'][0]['effective_morale'],62)
        self.assertEqual(next(h for h in housing(state)['homes'] if h['building_id']==bid)['capacity'],5)
        self.sql('UPDATE buildings SET origin_x=21 WHERE building_id=?',(bid,))
        self.assertEqual(self.state()['citizens'][0]['effective_morale'],63)

    def test_morale_clamps_and_productivity_uses_effective_value(self):
        self.enable();self.home('house',level=2)
        self.sql('UPDATE citizens SET morale=74 WHERE citizen_id=1')
        state=self.state()
        self.assertEqual(state['citizens'][0]['effective_morale'],77)
        self.assertAlmostEqual(productivity(state,state['citizens'][0]),1.1)
        self.assertAlmostEqual(resource_rates(state)['food']['production'],2.2)
        self.sql('UPDATE citizens SET morale=99 WHERE citizen_id=1')
        self.assertEqual(self.state()['citizens'][0]['effective_morale'],100)

    def test_health_changes_production_at_minute_boundaries(self):
        self.enable();self.sql('UPDATE citizens SET current_hp=75 WHERE citizen_id=1')
        apply_action(self.path,'resume',now=1000)
        before=resource_rates(self.state())['food']['production']
        self.assertEqual(advance_settlement(self.path,now=1059)['citizens'][0]['current_hp'],75)
        state=advance_settlement(self.path,now=1060)
        self.assertGreater(resource_rates(state)['food']['production'],before)
        self.assertAlmostEqual(state['citizens'][0]['current_hp'],75+2/60)

    def test_survivor_only_recovers_after_arrival(self):
        self.enable();self.survivor(fraction=.01)
        apply_action(self.path,'resume',now=1000)
        state=advance_settlement(self.path,now=1060)
        self.assertEqual(len(state['citizens']),7)
        self.assertAlmostEqual(state['citizens'][-1]['current_hp'],75+(60-27)*2/3600)

    def test_arbitrary_read_steps_equal_offline_catchup_and_restart(self):
        self.enable();self.sql('UPDATE citizens SET current_hp=75 WHERE citizen_id=1')
        apply_action(self.path,'resume',now=1000)
        other=Path(self.temp.name)/'other.db';prepare_database(other)
        with closing(connect_database(self.path)) as c,closing(connect_database(other)) as d:c.backup(d)
        one=advance_settlement(self.path,now=1603)
        for at in (1007,1059,1071,1133,1177,1222,1307,1403,1501,1603):many=advance_settlement(other,now=at)
        self.assertEqual(one['citizens'],many['citizens'])
        self.assertEqual(one['recovery_clock'],many['recovery_clock'])
        for r in ('food','water','scrap','metal','electronics'):self.assertAlmostEqual(one['resources'][r],many['resources'][r],places=8)
        self.assertEqual(one,advance_settlement(self.path,now=1603))
        prepare_database(self.path)
        self.assertEqual(one,read_settlement(self.path))

    def test_recovery_failure_rolls_back_resources_jobs_and_health(self):
        self.enable();self.sql('UPDATE citizens SET current_hp=75 WHERE citizen_id=1')
        apply_action(self.path,'resume',now=1000)
        self.sql("CREATE TRIGGER reject_heal BEFORE UPDATE OF current_hp ON citizens BEGIN SELECT RAISE(ABORT,'fixture'); END")
        before=self.state()
        with self.assertRaises(sqlite3.IntegrityError):advance_settlement(self.path,now=1060)
        self.assertEqual(before,self.state())

    def test_season_end_freezes_health(self):
        self.enable();self.sql('UPDATE citizens SET current_hp=75 WHERE citizen_id=2')
        self.sql('UPDATE seasons SET ends_at=1060,finalization_at=1000')
        apply_action(self.path,'resume',now=1000)
        state=advance_settlement(self.path,now=2000)
        self.assertEqual(state['season']['status'],'finished')
        self.assertAlmostEqual(state['citizens'][1]['current_hp'],75+2/60)
        self.assertEqual(state,advance_settlement(self.path,now=3000))

    def test_depletion_stops_healing_with_time(self):
        self.enable();self.sql('UPDATE citizens SET current_hp=75 WHERE citizen_id=2')
        self.sql('UPDATE settlement_resources SET food=4/60.0')
        apply_action(self.path,'resume',now=1000)
        state=advance_settlement(self.path,now=5000)
        self.assertEqual(state['season']['status'],'paused')
        self.assertEqual(state['season']['paused_at'],1060)
        self.assertAlmostEqual(state['citizens'][1]['current_hp'],75+2/60)
        self.assertEqual(state,advance_settlement(self.path,now=10000))

    def test_apartment_bonus_and_tent_morale_floor(self):
        self.enable();self.home('oxygen_garden',x=21,y=21)
        self.home('apartment_block',level=3)
        self.assertEqual(self.state()['citizens'][0]['effective_morale'],66)
        self.sql("UPDATE buildings SET status='demolished' WHERE building_type='apartment_block'")
        self.sql('UPDATE buildings SET current_hp=500 WHERE building_id=1')
        self.home('pup_tent')
        self.sql('UPDATE citizens SET morale=5 WHERE citizen_id=6')
        self.assertEqual(self.state()['citizens'][5]['effective_morale'],0)

    def test_rehousing_earns_only_eligible_partial_minute(self):
        self.enable();self.sql('UPDATE citizens SET current_hp=75 WHERE citizen_id=6')
        self.sql('UPDATE buildings SET current_hp=500 WHERE building_id=1')
        apply_action(self.path,'resume',now=1000)
        advance_settlement(self.path,now=1030)
        self.home('shack')
        state=advance_settlement(self.path,now=1060)
        self.assertAlmostEqual(state['citizens'][5]['current_hp'],75+30*2/3600)


class RecoveryHTTPTests(unittest.TestCase):
    setUp=prototype_tests.HTTPTests.setUp
    start_server=prototype_tests.HTTPTests.start_server
    stop_server=prototype_tests.HTTPTests.stop_server
    request=prototype_tests.HTTPTests.request
    create=prototype_tests.HTTPTests.create

    def test_enable_controls_morale_recovery_and_rejected_requests(self):
        self.create();before=read_settlement(self.path)
        def post(token):return self.request('POST','/buildings',urlencode({'action':'enable_recovery','token':token}),{'Content-Type':'application/x-www-form-urlencoded'})
        self.assertEqual(post('forged')[0],403)
        self.assertEqual(before,read_settlement(self.path))
        self.assertEqual(post(self.server.form_token)[0],303)
        status,_,page=self.request()
        self.assertEqual(status,200)
        self.assertIn('Citizen recovery status',page)
        self.assertIn('Morale',page)
        self.assertIn('At full health',page)
        self.assertNotIn('roll_pct',page)

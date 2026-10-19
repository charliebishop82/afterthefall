"""Civilian production, utility dependencies, shared storage, and raw-material recovery."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from app import PrototypeServer
from database.create_database import connect_database
from game.settlement import create_settlement,prepare_database,read_settlement,load_config
from game.buildings import change_building,operating_status,coverage,spec
from game.economy import utilities,storage,available_food
from game.simulation import advance_settlement,apply_action,resource_rates
from game.scavenging import assign,safe_coverage
from tests.fixtures import database_baseline,baseline_world
from tests import test_prototype as earlier
class ProductionTests(unittest.TestCase):
    def setUp(self):
        loot_seed=patch('game.scavenging.secrets.token_hex',return_value='seeded-test-loot')
        loot_seed.start();self.addCleanup(loot_seed.stop)
        world=baseline_world(self,'production',production_baseline)
        self.__dict__.update({k:v for k,v in vars(world).items() if not k.startswith('_') and k!='addCleanup'})
        self.temp=self.tmp

    def prepare_world(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'production.db'
        prepare_database(self.path);create_settlement(self.path,'Economy',now=1000)

    def sql(self,query,values=()):
        with closing(connect_database(self.path)) as c,c:return c.execute(query,values).fetchall()

    def state(self):return read_settlement(self.path)

    def enable(self):return change_building(self.path,'enable',now=1000)

    def fixture(self,kind,x=21,y=18,level=1,workers=(),hp=None):
        info=load_config('prototype_v4')['buildings'][kind];s=info['levels'][level-1]
        bid=self.sql('''INSERT INTO buildings(settlement_id,building_type,level,origin_x,origin_y,current_hp,status,created_at,completed_at)
            VALUES (1,?,?,?,?,?,'active',1000,1000) RETURNING building_id''',(kind,level,x,y,s['hp'] if hp is None else hp))[0][0]
        for citizen in workers:
            self.sql('''INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,building_id,assigned_at)
                VALUES (?,1,'production',?,1000)''',(citizen,bid))
            self.sql('UPDATE citizens SET unemployed_since=NULL WHERE citizen_id=?',(citizen,))
        return bid

    def fund(self):self.sql('UPDATE settlement_resources SET scrap=10000,metal=10000,electronics=10000')

    def test_all_catalog_levels_match_workbook_except_approved_unlock(self):
        c=load_config('prototype_v4');ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with ZipFile(Path(__file__).resolve().parents[1]/'sources'/c['sources']['workbook']) as z:
            rows=[]
            for row in ET.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//m:row',ns):
                rows.append({''.join(filter(str.isalpha,a.get('r'))):''.join(a.itertext()) if a.get('t')=='inlineStr' else a.findtext('m:v','',ns) for a in row})
        headers={label:column for column,label in rows[0].items()}
        fields={'workers':'Workers_Max','minutes':'Build_Time_Min','hp':'HP','scrap':'Scrap_Cost','metal':'Metal_Cost','electronics':'Electronics_Cost',
                'food':'Food_Output_per_Hr','water':'Water_Output_per_Hr','food_storage':'Food_Storage','water_storage':'Water_Storage',
                'material_storage':'Material_Storage','radius':'Utility_Radius_Tiles','oxygen_output':'Oxygen_Output','oxygen_demand':'Oxygen_Demand',
                'electricity_output':'Electricity_Output','electricity_demand':'Electricity_Demand','scrap_input':'Scrap_Input_per_Hr',
                'metal_input':'Metal_Input_per_Hr','metal_output':'Metal_Output_per_Hr','electronics_output':'Electronics_Output_per_Hr'}
        self.assertEqual(len(c['buildings']),20)
        for kind,info in c['buildings'].items():
            source=next(r for r in rows if r.get('A')==kind)
            self.assertEqual(info['unlock'],1 if kind=='warehouse' else int(source['D']))
            self.assertEqual(info['max_level'],int(source['F']))
            for level,s in enumerate(info['levels'],1):
                for k,field in fields.items():
                    # Retain workbook checks everywhere except the approved opening costs.
                    expected=float(source[headers[f'{field}_L{level}']] or 0)
                    if kind=='town_hall' and level==2:
                        expected={'scrap':150,'metal':50,'electronics':5}.get(k,expected)
                    self.assertEqual(s[k],expected,(kind,level,k))

    def test_enable_is_explicit_idempotent_and_preserves_old_supplies(self):
        before=self.state();state=self.enable()
        self.assertEqual(state['resources'],before['resources'])
        self.assertEqual(state['buildings'],before['buildings'])
        self.assertEqual(state['citizens'],before['citizens'])
        self.assertEqual(state['season']['config_version'],'prototype_v4')
        self.assertEqual(len(state['derelicts']),64)
        self.assertEqual(change_building(self.path,'enable',now=1000),state)
        self.assertEqual(self.sql('PRAGMA foreign_key_check'),[])

    def test_new_building_enables_economy_but_invalid_submission_rolls_back(self):
        before=self.state()
        with self.assertRaises(ValueError):change_building(self.path,'build',building_type='rain_collector',x=18,y=18,now=1000)
        self.assertEqual(self.state(),before)
        state=change_building(self.path,'build',building_type='rain_collector',x=21,y=18,now=1000)
        self.assertEqual(state['season']['config_version'],'prototype_v4')
        self.assertEqual(state['resources']['scrap'],155)

    def test_every_new_building_constructs_and_reaches_all_upgrade_levels(self):
        self.enable();self.fund()
        self.sql("UPDATE buildings SET level=3,current_hp=1900 WHERE building_id=1")
        self.sql("UPDATE settlement_derelicts SET status='cleared'")
        # Cases are independent, but each building still follows its complete
        # construction/upgrade chain through real elapsed simulation. Restore
        # once per building, not between levels, to retain that progression.
        baseline_buildings=self.sql('SELECT count(*) FROM buildings')[0][0]
        baseline_jobs=self.sql('SELECT count(*) FROM settlement_jobs')[0][0]
        with database_baseline(self.path) as restore:
            for kind,info in load_config('prototype_v4')['buildings'].items():
                if kind in load_config('prototype_v3')['buildings']:continue
                with self.subTest(kind=kind):
                    restore()
                    now=1000
                    self.assertEqual(self.sql('SELECT count(*) FROM buildings')[0][0],baseline_buildings)
                    self.assertEqual(self.sql('SELECT count(*) FROM settlement_jobs')[0][0],baseline_jobs)
                    state=change_building(self.path,'build',building_type=kind,x=21,y=18,now=now)
                    bid=state['buildings'][-1]['building_id']
                    for level in range(1,info['max_level']+1):
                        if level>1:change_building(self.path,'upgrade',building_id=bid,expected_level=level-1,now=now)
                        change_building(self.path,'builder',building_id=bid,citizen_id=2,now=now)
                        apply_action(self.path,'resume',now=now)
                        now+=int(info['levels'][level-1]['minutes']*60)
                        state=advance_settlement(self.path,now=now)
                        self.assertEqual(state['buildings'][-1]['level'],level)
                        self.assertEqual(state['buildings'][-1]['status'],'active')
                        self.assertEqual(state['citizens'][1]['assignment'],'unassigned')
                        apply_action(self.path,'pause',now=now)
                        self.sql('UPDATE settlement_resources SET food=120,water=120,scrap=10000,metal=10000,electronics=10000')
                    with self.assertRaises(ValueError):change_building(self.path,'upgrade',building_id=bid,expected_level=info['max_level'],now=now)
                    self.sql("UPDATE buildings SET status='demolished' WHERE building_id=?",(bid,))

    def test_rain_collectors_are_passive_and_stabilize_water(self):
        self.enable();self.fixture('rain_collector');self.fixture('rain_collector',x=22)
        state=self.state();self.assertEqual(resource_rates(state)['water']['production'],8)
        apply_action(self.path,'resume',now=1000);state=advance_settlement(self.path,now=4600)
        self.assertEqual(state['resources']['water'],122)
        with self.assertRaises(ValueError):change_building(self.path,'worker',building_id=2,citizen_id=2,now=4600)

    def test_water_worker_output_levels_damage_and_utility_priority(self):
        self.enable();self.sql('UPDATE buildings SET level=3,current_hp=1900 WHERE building_id=1')
        bid=self.fixture('well_pump',workers=(2,),level=2,hp=225)
        self.assertEqual(operating_status(self.state())[bid]['outputs']['water'],7.5)
        self.sql('UPDATE buildings SET current_hp=112.5 WHERE building_id=?',(bid,))
        self.assertEqual(operating_status(self.state())[bid]['outputs'],{})

    def test_union_coverage_from_multiple_sources_and_power_restart(self):
        self.enable();self.fixture('oxygen_garden',x=24,y=18)
        solar=self.fixture('solar_array',x=25,y=18)
        water=self.fixture('well_pump',x=27,y=18,workers=(2,))
        self.assertEqual(operating_status(self.state())[water]['outputs']['water'],9)
        self.sql('UPDATE buildings SET current_hp=0 WHERE building_id=?',(solar,))
        self.assertIn('electricity',operating_status(self.state())[water]['reason'])
        self.assertEqual(self.state()['citizens'][1]['assignment'],'production')
        self.sql('UPDATE buildings SET current_hp=220 WHERE building_id=?',(solar,))
        self.assertEqual(operating_status(self.state())[water]['outputs']['water'],9)

    def test_disconnected_oxygen_power_cycle_does_not_bootstrap(self):
        self.enable();self.fixture('generator_plant',x=2,y=2,workers=(2,));self.fixture('oxygen_generator',x=2,y=5)
        status=operating_status(self.state())
        self.assertTrue(status[2]['reason']);self.assertTrue(status[3]['reason'])

    def test_industrial_oxygen_requires_minimum_crew(self):
        self.enable();bid=self.fixture('industrial_oxygen',workers=(2,))
        self.assertIn('Requires 2',operating_status(self.state())[bid]['reason'])
        change_building(self.path,'worker',building_id=bid,citizen_id=3,now=1000)
        self.assertFalse(operating_status(self.state())[bid]['reason'])

    def test_recycler_recipe_input_exhaustion_stops_only_converter(self):
        self.enable();self.fixture('recycler',workers=(2,));self.sql('UPDATE settlement_resources SET scrap=5,metal=10')
        apply_action(self.path,'resume',now=1000);state=advance_settlement(self.path,now=4600)
        self.assertAlmostEqual(state['resources']['scrap'],0)
        self.assertAlmostEqual(state['resources']['metal'],13.5)
        self.assertEqual(state['season']['status'],'active')
        self.assertEqual(state['resources']['food'],116)
        self.assertIn('Waiting',operating_status(state)[2]['reason'])

    def test_electronics_requires_both_inputs_and_uses_config_recipe(self):
        self.enable();self.fixture('electronics_fabricator',workers=(2,));self.sql('UPDATE settlement_resources SET scrap=3,metal=6,electronics=0')
        apply_action(self.path,'resume',now=1000);state=advance_settlement(self.path,now=4600)
        self.assertAlmostEqual(state['resources']['scrap'],0)
        self.assertAlmostEqual(state['resources']['metal'],3)
        self.assertAlmostEqual(state['resources']['electronics'],1)
        self.assertEqual(state['season']['status'],'active')

    def test_shared_material_storage_and_increase_from_scrap_yard(self):
        self.enable();self.assertEqual(storage(self.state())['material'],250)
        self.fixture('scrap_yard');self.assertEqual(storage(self.state())['material'],500)
        self.fixture('warehouse',x=15,y=18,level=2);self.assertEqual(storage(self.state())['material'],1200)

    def test_cold_storage_unpowered_food_retained_inaccessible_and_restored(self):
        self.enable();bid=self.fixture('cold_storage',x=0,y=0)
        self.sql('UPDATE settlement_resources SET food=300')
        self.assertEqual(storage(self.state())['food'],205)
        apply_action(self.path,'resume',now=1000)
        first=advance_settlement(self.path,now=4600)
        self.assertEqual(first['resources']['food'],296)
        self.assertEqual(first['storage_lock']['protected_food'],95)
        second=advance_settlement(self.path,now=8200)
        self.assertEqual(second['resources']['food'],292)
        self.assertEqual(available_food(second),197)
        self.fixture('solar_array',x=0,y=3)
        self.assertEqual(available_food(self.state()),292)

    def test_initial_derelicts_do_not_overlap_existing_or_each_other(self):
        state=self.enable();occupied=[]
        for d in state['derelicts']:
            w,h=state['config']['derelicts'][d['derelict_type']]['footprint'];x,y=d['origin_x'],d['origin_y']
            self.assertLessEqual(x+w,40);self.assertLessEqual(y+h,40)
            self.assertFalse(x<21 and x+w>18 and y<21 and y+h>18)
            self.assertFalse(any(x<ox+ow and x+w>ox and y<oy+oh and y+h>oy for ox,oy,ow,oh in occupied))
            occupied.append((x,y,w,h))
        self.assertTrue(all(safe_coverage(state,d)>=state['config']['construction']['coverage_fraction'] for d in state['derelicts'][:4]))

    def loot_fixture(self):
        self.enable();d=self.state()['derelicts'][0]
        loot={'food':6,'water':6,'scrap':24,'metal':6,'electronics':1}
        self.sql('UPDATE settlement_derelicts SET random_result=? WHERE settlement_derelict_id=?',(json.dumps(loot),d['settlement_derelict_id']))
        return d['settlement_derelict_id'],loot

    def test_scavenging_delivers_gradually_clears_releases_and_never_duplicates(self):
        did,loot=self.loot_fixture();assign(self.path,'assign',did,2,now=1000)
        apply_action(self.path,'resume',now=1000)
        half=advance_settlement(self.path,now=2350)
        self.assertAlmostEqual(half['resources']['scrap'],192)
        self.assertAlmostEqual(half['resources']['food'],121.5)
        result=advance_settlement(self.path,now=3700)
        self.assertEqual(result['derelicts'][0]['status'],'cleared')
        self.assertEqual(result['citizens'][1]['assignment'],'unassigned')
        self.assertEqual(advance_settlement(self.path,now=3700),result)
        self.assertEqual(json.loads(result['derelicts'][0]['random_result']),loot)
        with self.assertRaises(ValueError):assign(self.path,'assign',did,2,now=3700)

    def test_scavenging_stops_without_workers_and_ignores_paused_time(self):
        did,_=self.loot_fixture();assign(self.path,'assign',did,2,now=1000);apply_action(self.path,'resume',now=1000)
        assign(self.path,'release',did,2,now=1300)
        self.assertEqual(advance_settlement(self.path,now=1600)['jobs'][0]['work_completed'],300)
        assign(self.path,'assign',did,3,now=1600);apply_action(self.path,'pause',now=1900)
        self.assertEqual(advance_settlement(self.path,now=5000)['jobs'][0]['work_completed'],600)

    def test_scavenging_material_overflow_is_discarded_without_duplicate_recovery(self):
        did,_=self.loot_fixture();self.sql('UPDATE settlement_resources SET scrap=200,metal=40,electronics=10')
        assign(self.path,'assign',did,2,now=1000);apply_action(self.path,'resume',now=1000)
        state=advance_settlement(self.path,now=3700)
        self.assertAlmostEqual(sum(state['resources'][r] for r in ('scrap','metal','electronics')),250)
        self.assertEqual(state['derelicts'][0]['status'],'cleared')

    def test_scavenging_foreign_occupied_unsafe_and_full_crew_actions_roll_back(self):
        state=self.enable();safe=state['derelicts'][0]['settlement_derelict_id']
        unsafe=next(d['settlement_derelict_id'] for d in state['derelicts'] if safe_coverage(state,d)<state['config']['construction']['coverage_fraction'])
        for did,cid in [(safe,1),(unsafe,2),(999,2),(safe,999)]:
            before=self.state()
            with self.assertRaises(ValueError):assign(self.path,'assign',did,cid,now=1000)
            self.assertEqual(self.state(),before)
        for cid in (2,3,4):assign(self.path,'assign',safe,cid,now=1000)
        with self.assertRaises(ValueError):assign(self.path,'assign',safe,5,now=1000)

    def test_loot_values_are_persisted_within_reference_ranges(self):
        state=self.enable()
        for d in state['derelicts']:
            result=json.loads(d['random_result']);ranges=state['config']['derelicts'][d['derelict_type']]['loot']
            for r,v in result.items():self.assertTrue(ranges[r][0]<=v<=ranges[r][1])
        self.assertEqual(advance_settlement(self.path,now=10000),state)

    def test_material_input_offline_step_equivalence(self):
        self.enable();self.fixture('recycler',workers=(2,));self.sql('UPDATE settlement_resources SET scrap=5')
        apply_action(self.path,'resume',now=1000)
        other=Path(self.temp.name)/'copy.db'
        with closing(connect_database(self.path)) as a,closing(sqlite3.connect(other)) as b:a.backup(b)
        large=advance_settlement(self.path,now=4600)
        for now in range(1300,4601,300):small=advance_settlement(other,now=now)
        for r in ('food','water','scrap','metal','electronics'):self.assertAlmostEqual(large['resources'][r],small['resources'][r],places=8)

    def test_arriving_scavenged_inputs_feed_converter_without_zero_pool_toggling(self):
        did,_=self.loot_fixture();self.fixture('recycler',workers=(2,))
        self.sql('UPDATE settlement_resources SET scrap=0')
        assign(self.path,'assign',did,3,now=1000);apply_action(self.path,'resume',now=1000)
        other=Path(self.temp.name)/'copy.db'
        with closing(connect_database(self.path)) as a,closing(sqlite3.connect(other)) as b:a.backup(b)
        large=advance_settlement(self.path,now=4600)
        for now in range(1300,4601,300):small=advance_settlement(other,now=now)
        self.assertAlmostEqual(large['resources']['scrap'],14)
        self.assertAlmostEqual(large['resources']['metal'],53)
        for r in ('food','water','scrap','metal','electronics'):self.assertAlmostEqual(large['resources'][r],small['resources'][r],places=8)

    def test_cold_storage_pause_keeps_locked_food_and_rejects_resume(self):
        self.enable();self.fixture('cold_storage',x=0,y=0)
        self.sql('UPDATE settlement_resources SET food=300,water=1000')
        self.fixture('rain_collector',x=21);self.fixture('rain_collector',x=22)
        apply_action(self.path,'resume',now=1000)
        result=advance_settlement(self.path,now=300000)
        self.assertEqual(result['season']['status'],'paused')
        self.assertEqual(result['resources']['food'],95)
        self.assertEqual(available_food(result),0)
        with self.assertRaises(ValueError):apply_action(self.path,'resume',now=300000)

    def test_storage_and_conversion_catch_up_are_rolled_back_on_failure(self):
        self.enable();self.fixture('recycler',workers=(2,));apply_action(self.path,'resume',now=1000)
        before=self.state()
        self.sql("CREATE TRIGGER fail_progress BEFORE UPDATE ON settlements BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):advance_settlement(self.path,now=4600)
        self.assertEqual(self.state(),before)


class ProductionHTTPTests(unittest.TestCase):
    request=earlier.HTTPTests.request

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'http.db';prepare_database(self.path);create_settlement(self.path,'Civilian Test',now=1000)
        self.server=PrototypeServer(('127.0.0.1',0),self.path,clock=lambda:1000)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':0.01},daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)

    def test_enable_catalog_scavenging_forms_and_no_private_loot_exposure(self):
        header={'Content-Type':'application/x-www-form-urlencoded'}
        body=urlencode({'token':self.server.form_token,'action':'enable'})
        self.assertEqual(self.request('POST','/buildings',body,header)[0],303)
        page=self.request()[2]
        for text in ('Rain Collector','Recycler','Warehouse','Scavenging &amp; capacity','Enable civilian'):
            if text=='Enable civilian':self.assertNotIn(text,page)
            else:self.assertIn(text,page)
        payload=self.request(path='/api/resources')[2]
        self.assertNotIn('random_nonce',payload);self.assertNotIn('random_result',payload)
        self.assertNotIn('random_nonce',page);self.assertNotIn('random_result',page)
        body=urlencode({'token':self.server.form_token,'action':'assign','derelict_id':1,'citizen_id':2})
        self.assertEqual(self.request('POST','/scavenging',body,header)[0],303)
        self.assertEqual(self.request('POST','/scavenging',body.replace(self.server.form_token,'wrong'),header)[0],403)


def production_baseline(owner):
    world=ProductionTests()
    world.addCleanup=owner.addCleanup
    world.prepare_world()
    return world

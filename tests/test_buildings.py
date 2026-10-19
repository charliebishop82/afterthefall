"""Construction, Food, Town Hall upgrades, and their interactions with the clock."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.parse import urlencode
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from app import PrototypeServer
from database.create_database import connect_database
from game.buildings import change_building, coverage, job_speed, operating_status, spec
from game.settlement import create_settlement, load_config, prepare_database, read_settlement
from game.simulation import advance_settlement, apply_action, resource_rates
from tests import test_prototype as prototype_tests
class BuildingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'food.db'
        prepare_database(self.path)
        create_settlement(self.path, 'Food Test', now=1000)

    def query(self, sql, params=()):
        with closing(connect_database(self.path)) as c, c:
            return c.execute(sql, params).fetchall()

    def state(self):
        return read_settlement(self.path)

    def command(self, action, now=1000, **kw):
        return change_building(self.path, action, now=now, **kw)

    def build(self, kind='garden', x=21, y=18, now=1000, rotation=0):
        return self.command('build', now, building_type=kind, x=x, y=y, rotation=rotation)['buildings'][-1]['building_id']

    def fund(self):
        # Explicit test fixtures; never connected to a player save or UI.
        self.query('UPDATE settlement_resources SET scrap=10000,metal=10000,electronics=10000')

    def unlock(self, level=3):
        self.query("UPDATE seasons SET config_version='prototype_v3'")
        hp = load_config('prototype_v3')['buildings']['town_hall']['levels'][level-1]['hp']
        self.query('UPDATE buildings SET level=?,current_hp=? WHERE building_type=?', (level, hp, 'town_hall'))
        self.fund()

    def finish(self, bid, worker=2, now=1000):
        state = self.command('builder', now, building_id=bid, citizen_id=worker)
        job = next(j for j in state['jobs'] if j['target_building_id']==bid and j['status'] in ('active','paused'))
        apply_action(self.path, 'resume', now=now)
        end = now + int(job['work_required'])
        return advance_settlement(self.path, now=end), end

    def test_catalog_values_match_workbook(self):
        root = Path(__file__).resolve().parents[1]
        config = load_config('prototype_v3')
        ns = {'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with ZipFile(root/'sources'/config['sources']['workbook']) as z:
            rows = []
            for row in ET.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//s:row',ns):
                rows.append({''.join(filter(str.isalpha,c.get('r'))):
                    ''.join(c.itertext()) if c.get('t')=='inlineStr' else c.findtext('s:v','',ns) for c in row})
        headers = {value:key for key,value in rows[0].items()}
        names = {'workers':'Workers_Max','minutes':'Build_Time_Min','hp':'HP','scrap':'Scrap_Cost',
                 'metal':'Metal_Cost','electronics':'Electronics_Cost','food':'Food_Output_per_Hr',
                 'water':'Water_Output_per_Hr','food_storage':'Food_Storage','water_storage':'Water_Storage',
                 'material_storage':'Material_Storage','housing':'Housing_Capacity','radius':'Utility_Radius_Tiles',
                 'electricity_demand':'Electricity_Demand','electricity_output':'Electricity_Output',
                 'oxygen_demand':'Oxygen_Demand','oxygen_output':'Oxygen_Output'}
        for kind, item in config['buildings'].items():
            row = next(r for r in rows if r.get('A')==kind)
            self.assertEqual(item['unlock'],int(row['D']))
            self.assertEqual(item['footprint'],list(map(int,row['E'].split('x'))))
            self.assertEqual(item['max_level'],int(row['F']))
            for level,s in enumerate(item['levels'],1):
                for key,label in names.items():
                    # Approved opening balance: only these three Hall level-2 costs differ.
                    expected=float(row[headers[f'{label}_L{level}']] or 0)
                    if kind=='town_hall' and level==2:
                        expected={'scrap':150,'metal':50,'electronics':5}.get(key,expected)
                    self.assertEqual(s[key],expected,(kind,level,key))

    def test_site_spends_once_reserves_tiles_and_upgrades_config_only_on_action(self):
        self.assertEqual(self.state()['season']['config_version'],'prototype_v1')
        bid = self.build()
        state = self.state()
        self.assertEqual(state['season']['config_version'],'prototype_v3')
        self.assertEqual(state['resources']['scrap'],145)
        self.assertEqual(state['resources']['metal'],40)
        self.assertEqual(state['buildings'][-1]['current_hp'],0)
        self.assertEqual(state['jobs'][0]['work_required'],900)
        with self.assertRaises(ValueError):self.build()
        self.assertEqual(self.state(),state)
        self.assertEqual(self.query('PRAGMA foreign_key_check'),[])

    def test_invalid_placement_unlock_and_rotation_preserve_save(self):
        for kw in [dict(x=-1),dict(x=39),dict(x=18,y=18),dict(rotation=45),dict(kind='greenhouse'),dict(kind='hydroponics'),dict(kind='unknown')]:
            before = self.state()
            with self.assertRaises(ValueError):self.build(**kw)
            self.assertEqual(self.state(),before)
        self.build(x=38,y=38)

    def test_rotated_rectangular_footprint_and_overlap(self):
        self.unlock()
        with self.assertRaises(ValueError):self.build('greenhouse',x=38,y=30,rotation=90)
        self.build('greenhouse',x=37,y=38,rotation=90)
        with self.assertRaises(ValueError):self.build(x=38,y=38)

    def test_insufficient_materials_rolls_back_without_config_change(self):
        self.query('UPDATE settlement_resources SET scrap=34')
        before = self.state()
        with self.assertRaises(ValueError):self.build()
        self.assertEqual(self.state(),before)

    def test_no_workers_no_progress_and_no_free_output(self):
        bid = self.build()
        apply_action(self.path,'resume',now=1000)
        state = advance_settlement(self.path,now=4600)
        self.assertEqual(state['jobs'][0]['work_completed'],0)
        self.assertEqual(state['buildings'][-1]['current_hp'],0)
        self.assertEqual(state['resources']['food'],116)
        with self.assertRaises(ValueError):self.command('worker',4600,building_id=bid,citizen_id=2)

    def test_construction_partial_hp_completion_release_and_persistence(self):
        bid = self.build()
        self.command('builder',building_id=bid,citizen_id=2)
        apply_action(self.path,'resume',now=1000)
        half = advance_settlement(self.path,now=1450)
        self.assertEqual(half['jobs'][0]['work_completed'],450)
        self.assertEqual(half['buildings'][-1]['current_hp'],75)
        result = advance_settlement(self.path,now=1900)
        self.assertEqual(result['jobs'][0]['status'],'completed')
        self.assertEqual(result['buildings'][-1]['current_hp'],150)
        self.assertEqual(result['citizens'][1]['assignment'],'unassigned')
        self.assertEqual(resource_rates(result)['food']['production'],2)
        self.assertEqual(resource_rates(result)['food']['capacity'],160)
        prepare_database(self.path)
        self.assertEqual(advance_settlement(self.path,now=1900),result)

    def test_workers_output_capacity_limits_and_release(self):
        bid = self.build()
        _, now = self.finish(bid)
        state = self.command('worker',now,building_id=bid,citizen_id=2)
        self.assertEqual(resource_rates(state)['food']['production'],8)
        state = self.command('worker',now,building_id=bid,citizen_id=3)
        self.assertEqual(resource_rates(state)['food']['production'],14)
        with self.assertRaises(ValueError):self.command('worker',now,building_id=bid,citizen_id=4)
        self.assertEqual(self.command('worker',now,building_id=bid,citizen_id=3),state)
        grown = advance_settlement(self.path,now=now+3600)
        self.assertAlmostEqual(grown['resources']['food'],127)
        removed = self.command('release',now+3600,building_id=bid,citizen_id=3)
        self.assertEqual(resource_rates(removed)['food']['production'],8)
        self.assertEqual(removed['resources']['food'],127)
        self.query('UPDATE settlement_resources SET food=159')
        self.assertEqual(advance_settlement(self.path,now=now+7200)['resources']['food'],160)

    def test_releasing_all_builders_pauses_work_without_losing_progress(self):
        bid = self.build()
        self.command('builder',building_id=bid,citizen_id=2)
        apply_action(self.path,'resume',now=1000)
        state = self.command('release',1300,building_id=bid,citizen_id=2)
        self.assertEqual(state['jobs'][0]['work_completed'],300)
        self.assertEqual(advance_settlement(self.path,now=2000)['jobs'][0]['work_completed'],300)
        self.command('builder',2000,building_id=bid,citizen_id=3)
        self.assertEqual(advance_settlement(self.path,now=2600)['jobs'][0]['status'],'completed')

    def test_extra_builders_have_diminishing_returns(self):
        bid = self.build()
        one = self.command('builder',building_id=bid,citizen_id=2)
        one_speed = job_speed(one,one['jobs'][0])
        two = self.command('builder',building_id=bid,citizen_id=3)
        self.assertGreater(job_speed(two,two['jobs'][0]),one_speed)
        self.assertLess(job_speed(two,two['jobs'][0]),one_speed*2)

    def test_pause_resume_excludes_paused_time_from_projects(self):
        bid = self.build()
        self.command('builder',building_id=bid,citizen_id=2)
        apply_action(self.path,'resume',now=1000)
        apply_action(self.path,'pause',now=1300)
        self.assertEqual(advance_settlement(self.path,now=5000)['jobs'][0]['work_completed'],300)
        apply_action(self.path,'resume',now=5000)
        self.assertEqual(advance_settlement(self.path,now=5600)['jobs'][0]['completed_at'],5600)

    def test_upgrade_cost_level_cap_slots_and_old_output_until_start(self):
        self.unlock(2)
        bid = self.build('greenhouse')
        _, now = self.finish(bid)
        self.command('worker',now,building_id=bid,citizen_id=2)
        self.command('worker',now,building_id=bid,citizen_id=3)
        before = self.state()
        upgraded = self.command('upgrade',now+600,building_id=bid,expected_level=1)
        self.assertAlmostEqual(upgraded['resources']['food'],before['resources']['food']+17/6)
        self.assertEqual(upgraded['resources']['scrap'],before['resources']['scrap']-70)
        self.assertEqual(resource_rates(upgraded)['food']['production'],3)
        with self.assertRaises(ValueError):self.command('upgrade',now+600,building_id=bid,expected_level=1)
        result, end = self.finish(bid,worker=4,now=now+600)
        self.assertEqual(result['buildings'][-1]['level'],2)
        self.assertEqual(resource_rates(result)['food']['production'],37)
        state = self.command('worker',end,building_id=bid,citizen_id=4)
        self.assertEqual(operating_status(state)[bid]['workers'],3)
        self.command('upgrade',end,building_id=bid,expected_level=2)
        result,end = self.finish(bid,worker=5,now=end)
        self.assertEqual(result['buildings'][-1]['level'],3)
        with self.assertRaises(ValueError):self.command('upgrade',end,building_id=bid,expected_level=3)

    def test_garden_has_no_invented_upgrade(self):
        bid = self.build()
        _, now = self.finish(bid)
        with self.assertRaises(ValueError):self.command('upgrade',now,building_id=bid,expected_level=1)

    def test_town_hall_upgrades_unlock_both_food_tiers(self):
        self.fund()
        state = self.command('upgrade',building_id=1,expected_level=1)
        self.assertEqual(resource_rates(state)['food']['production'],1)
        state, now = self.finish(1)
        self.assertEqual(state['buildings'][0]['level'],2)
        self.assertEqual(resource_rates(state)['food']['production'],3)
        self.assertEqual(resource_rates(state)['food']['capacity'],225)
        self.assertEqual(spec(state,state['buildings'][0])['housing'],12)
        self.build('greenhouse',now=now)
        with self.assertRaises(ValueError):self.build('hydroponics',x=15,now=now)
        self.command('upgrade',now,building_id=1,expected_level=2)
        state, now = self.finish(1,now=now)
        self.assertEqual(state['buildings'][0]['level'],3)
        self.build('hydroponics',x=15,now=now)

    def test_hydroponics_all_upgrade_levels_and_staff_caps(self):
        self.unlock(3)
        bid = self.build('hydroponics')
        state, now = self.finish(bid)
        for level, expected in [(1,18),(2,30),(3,45)]:
            state = self.command('worker',now,building_id=bid,citizen_id=3)
            self.assertEqual(operating_status(state)[bid]['output'],expected)
            if level < 3:
                self.command('upgrade',now,building_id=bid,expected_level=level)
                state,now = self.finish(bid,now=now)
        with self.assertRaises(ValueError):self.command('upgrade',now,building_id=bid,expected_level=3)

    def test_upgrade_stale_level_rejected_after_completion(self):
        self.fund()
        self.command('upgrade',building_id=1,expected_level=1)
        _,now = self.finish(1)
        before = self.state()
        with self.assertRaises(ValueError):self.command('upgrade',now,building_id=1,expected_level=1)
        self.assertEqual(self.state(),before)

    def test_utility_coverage_and_unsafe_site(self):
        state = self.state()
        b = dict(building_type='garden',level=1,origin_x=24,origin_y=18,rotation=0)
        self.assertEqual(coverage(state,b),.5)
        bid = self.build(x=0,y=0)
        with self.assertRaises(ValueError):self.command('builder',building_id=bid,citizen_id=2)
        self.assertEqual(self.state()['citizens'][1]['assignment'],'unassigned')

    def test_capacity_shortage_idles_workers_and_recovers(self):
        self.unlock(3)
        first = self.build('hydroponics',x=21,y=18)
        _,now = self.finish(first)
        self.command('worker',now,building_id=first,citizen_id=3)
        self.command('upgrade',now,building_id=first,expected_level=1)
        _,now=self.finish(first,now=now)
        self.command('upgrade',now,building_id=first,expected_level=2)
        _,now=self.finish(first,now=now)
        second=self.build('greenhouse',x=15,y=18,now=now)
        _,now=self.finish(second,now=now)
        state=self.command('worker',now,building_id=second,citizen_id=4)
        self.assertIn('electricity',operating_status(state)[second]['reason'])
        self.command('release',now,building_id=first,citizen_id=3)
        self.assertEqual(operating_status(self.state())[second]['output'],10)

    def test_damage_and_citizen_condition_modify_food_output(self):
        bid=self.build(); _,now=self.finish(bid)
        self.command('worker',now,building_id=bid,citizen_id=2)
        self.query('UPDATE citizens SET current_hp=50 WHERE citizen_id=2')
        self.query('UPDATE buildings SET current_hp=75 WHERE building_id=?',(bid,))
        self.assertEqual(operating_status(self.state())[bid]['output'],1.5)
        self.query('UPDATE buildings SET current_hp=37.5 WHERE building_id=?',(bid,))
        self.assertEqual(operating_status(self.state())[bid]['output'],0)

    def test_invalid_staffing_and_transaction_rollback(self):
        bid=self.build()
        for citizen in (1,999):
            before=self.state()
            with self.assertRaises(ValueError):self.command('builder',building_id=bid,citizen_id=citizen)
            self.assertEqual(self.state(),before)
        self.query("CREATE TRIGGER fail_job BEFORE INSERT ON settlement_jobs BEGIN SELECT RAISE(ABORT,'test'); END")
        before=self.state()
        with self.assertRaises(sqlite3.IntegrityError):self.build(x=15)
        self.assertEqual(self.state(),before)

    def test_concurrent_placement_spends_only_once(self):
        def attempt(_):
            try:return self.build()
            except ValueError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,range(2)))
        self.assertEqual(sum(r is not None for r in results),1)
        self.assertEqual(self.state()['resources']['scrap'],145)

    def test_completion_boundary_offline_matches_small_steps(self):
        self.fund()
        self.command('upgrade',building_id=1,expected_level=1)
        self.command('builder',building_id=1,citizen_id=2)
        apply_action(self.path,'resume',now=1000)
        other=Path(self.temp.name)/'copy.db'
        with closing(connect_database(self.path)) as a, closing(sqlite3.connect(other)) as b:a.backup(b)
        large=advance_settlement(self.path,now=11800)
        for now in range(1300,11801,300):small=advance_settlement(other,now=now)
        self.assertAlmostEqual(large['resources']['food'],107)
        self.assertAlmostEqual(large['resources']['food'],small['resources']['food'],places=8)
        self.assertEqual(large['jobs'],small['jobs'])

    def test_depletion_stops_construction_at_boundary(self):
        bid=self.build(); self.command('builder',building_id=bid,citizen_id=2)
        self.query('UPDATE settlement_resources SET water=0.5')
        apply_action(self.path,'resume',now=1000)
        state=advance_settlement(self.path,now=5000)
        self.assertEqual(state['season']['paused_at'],1450)
        self.assertEqual(state['jobs'][0]['work_completed'],450)

    def test_final_window_rejects_new_projects_and_season_end_freezes_existing(self):
        bid=self.build(); self.command('builder',building_id=bid,citizen_id=2)
        self.query('UPDATE seasons SET finalization_at=1000,ends_at=1600')
        with self.assertRaises(ValueError):self.build(x=15)
        self.fund()
        with self.assertRaises(ValueError):self.command('upgrade',building_id=1,expected_level=1)
        apply_action(self.path,'resume',now=1000)
        state=advance_settlement(self.path,now=3000)
        self.assertEqual(state['jobs'][0]['work_completed'],600)
        self.assertEqual(state['jobs'][0]['status'],'cancelled')
        self.assertEqual(advance_settlement(self.path,now=4000),state)


class BuildingHttpTests(unittest.TestCase):
    request=prototype_tests.HTTPTests.request

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'http.db'
        prepare_database(self.path); create_settlement(self.path,'Browser Test',now=1000)
        self.now=1000
        self.server=PrototypeServer(('127.0.0.1',0),self.path,clock=lambda:self.now)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':0.01},daemon=True); self.thread.start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)

    def post(self, **values):
        return self.request('POST','/buildings',urlencode({'token':self.server.form_token,**values}),{'Content-Type':'application/x-www-form-urlencoded'})

    def test_browser_build_assign_finish_work_release_flow(self):
        self.assertEqual(self.post(action='build',building_type='garden',x=21,y=18,rotation=0)[0],303)
        self.assertEqual(self.post(action='builder',building_id=2,citizen_id=2)[0],303)
        apply_action(self.path,'resume',now=1000); self.now=1900
        payload=json.loads(self.request(path='/api/resources')[2])
        self.assertIn('revision',payload)
        self.assertEqual(self.post(action='worker',building_id=2,citizen_id=2)[0],303)
        page=self.request()[2]
        for text in ('Garden #2','+6 Food/hour','Release Elias Reed','160','placement-preview'):
            self.assertIn(text,page)
        self.assertEqual(self.post(action='release',building_id=2,citizen_id=2)[0],303)
        self.assertEqual(self.request(path='/static/buildings.js')[0],200)
        self.assertEqual(self.request(path='/static/buildings.css')[0],200)

    def test_http_invalid_input_and_forged_token_leave_save_unchanged(self):
        before=read_settlement(self.path)
        self.assertEqual(self.post(action='build',building_type='garden',x='no',y=18)[0],400)
        self.assertEqual(self.post(action='build',building_type='greenhouse',x=21,y=18)[0],400)
        self.assertEqual(self.post(action='upgrade',building_id=1,expected_level=1)[0],400)
        self.assertEqual(self.post(action='build',token='wrong',building_type='garden',x=21,y=18)[0],403)
        self.assertEqual(read_settlement(self.path),before)

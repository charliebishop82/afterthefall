"""Work XP, saved credit, progression boundaries and legacy compatibility."""
import unittest
from contextlib import closing
import sqlite3
import test_population as fixtures
from game.buildings import change_building,productivity
from game.simulation import apply_action,advance_settlement
from game.settlement import load_config
from game.progression import hourly_rates
from game.views import render_page
from database.create_database import connect_database

class ProgressionTests(unittest.TestCase):
    setUp=fixtures.PopulationTests.setUp
    state=fixtures.PopulationTests.state
    sql=fixtures.PopulationTests.sql
    home=fixtures.PopulationTests.home
    def enable(self):return change_building(self.path,'enable_progression',now=1000)
    def run_to(self,now):
        apply_action(self.path,'resume',now=1000)
        return advance_settlement(self.path,now=now)
    def test_explicit_enable_preserves_and_cannot_downgrade(self):
        change_building(self.path,'enable_recovery',now=1000);before=self.state();after=self.enable()
        for key in ('resources','citizens','derelicts','jobs'):self.assertEqual(before[key],after[key])
        for action in ('enable_progression','enable_recovery','enable_housing','enable'):
            self.assertEqual(after,change_building(self.path,action,now=1000))
    def test_workbook_thresholds_and_legacy_config(self):
        rules=load_config('prototype_v7')['progression']
        self.assertEqual(rules['thresholds'],[0,100,250,450,700,1000,1350,1750,2200,2700])
        self.assertEqual(rules['work_xp_per_hour'],1);self.assertEqual(rules['construction_xp_per_hour'],2)
        self.assertNotIn('progression',load_config('prototype_v6'))
        self.assertEqual(load_config('prototype_v6')['buildings'],load_config('prototype_v7')['buildings'])
    def test_administrator_earns_and_idle_citizens_do_not(self):
        self.enable();state=self.run_to(4600)
        self.assertAlmostEqual(state['citizens'][0]['xp'],1)
        self.assertTrue(all(c['xp']==0 for c in state['citizens'][1:]))
    def test_previous_version_still_earns_no_xp(self):
        change_building(self.path,'enable_recovery',now=1000)
        self.assertEqual(self.run_to(4600)['citizens'][0]['xp'],0)
    def test_level_threshold_history_and_no_free_healing(self):
        self.enable();self.sql('UPDATE citizens SET xp=99.99 WHERE citizen_id=1')
        state=self.run_to(1060);c=state['citizens'][0]
        self.assertEqual(c['level'],2);self.assertEqual(c['max_hp'],108);self.assertEqual(c['current_hp'],100)
        self.assertEqual(len(self.sql('SELECT * FROM citizen_level_history WHERE citizen_id=1 AND level=2')),1)
        before=c['xp'];state=advance_settlement(self.path,now=1120)
        self.assertGreater(state['citizens'][0]['xp'],before)
        self.assertEqual(len(self.sql('SELECT * FROM citizen_level_history WHERE citizen_id=1 AND level=2')),1)
    def test_level_ten_cap_multiple_thresholds(self):
        self.enable();self.sql('UPDATE citizens SET xp=2700 WHERE citizen_id=1')
        state=self.run_to(1060)
        self.assertEqual(state['citizens'][0]['level'],10)
        self.assertEqual(len(self.sql('SELECT * FROM citizen_level_history WHERE citizen_id=1')),10)
        self.assertEqual(advance_settlement(self.path,now=1120)['citizens'][0]['level'],10)
    def test_partial_credit_pause_and_restart(self):
        self.enable();apply_action(self.path,'resume',now=1000);apply_action(self.path,'pause',now=1010)
        self.assertEqual(self.state()['citizens'][0]['xp'],0)
        self.assertAlmostEqual(self.state()['xp_clock']['pending']['1'],10/3600)
        self.assertEqual(advance_settlement(self.path,now=2000)['citizens'][0]['xp'],0)
        apply_action(self.path,'resume',now=2010)
        self.assertAlmostEqual(advance_settlement(self.path,now=2060)['citizens'][0]['xp'],1/60)
    def test_repeated_reads_equal_offline_progress(self):
        self.enable();self.sql('UPDATE citizens SET xp=99.99 WHERE citizen_id=1');apply_action(self.path,'resume',now=1000)
        alternate=self.path.with_name('offline.db')
        with closing(sqlite3.connect(self.path)) as a,closing(sqlite3.connect(alternate)) as b:a.backup(b)
        for now in (1007,1059,1061,1079,1121,1301,1603):advance_settlement(self.path,now=now)
        one=advance_settlement(alternate,now=1603);many=self.state()
        for c,d in zip(one['citizens'],many['citizens']):
            self.assertEqual(c['level'],d['level']);self.assertAlmostEqual(c['xp'],d['xp']);self.assertAlmostEqual(c['current_hp'],d['current_hp'])
        for r in ('food','water'):self.assertAlmostEqual(one['resources'][r],many['resources'][r])
    def test_builder_awards_actual_work_and_stops_at_completion(self):
        self.enable();self.sql('DELETE FROM settlement_derelicts');self.sql('DELETE FROM season_derelicts')
        state=change_building(self.path,'build',building_type='garden',x=21,y=18,now=1000);bid=state['buildings'][-1]['building_id']
        change_building(self.path,'builder',building_id=bid,citizen_id=2,now=1000)
        state=self.run_to(2800)
        self.assertAlmostEqual(state['citizens'][1]['xp'],.5)
        self.assertEqual(state['citizens'][1]['assignment'],'unassigned')
    def test_production_stalls_without_utilities(self):
        self.enable();bid=self.home('garden');change_building(self.path,'worker',building_id=bid,citizen_id=2,now=1000)
        state=self.run_to(1060);self.assertAlmostEqual(state['citizens'][1]['xp'],1/60)
        self.sql('UPDATE buildings SET origin_x=0,origin_y=0 WHERE building_id=?',(bid,))
        state=advance_settlement(self.path,now=1120);self.assertAlmostEqual(state['citizens'][1]['xp'],1/60)
    def test_scavenging_earns_until_complete(self):
        self.enable()
        from game.scavenging import assign
        d=self.state()['derelicts'][0];assign(self.path,'assign',d['settlement_derelict_id'],2,now=1000)
        job=self.state()['jobs'][0];state=self.run_to(4600)
        self.assertAlmostEqual(state['citizens'][1]['xp'],job['work_required']/3600)
    def test_failed_xp_write_rolls_back_everything(self):
        self.enable();apply_action(self.path,'resume',now=1000);before=self.state()
        self.sql("CREATE TRIGGER fail_xp BEFORE UPDATE OF xp ON citizens BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):advance_settlement(self.path,now=1060)
        self.assertEqual(self.state(),before)
    def test_ui_shows_xp_and_activation_state(self):
        self.assertIn('Enable citizen progression',render_page(self.state(),'token').decode())
        self.enable();html=render_page(self.state(),'token').decode()
        self.assertIn('0.00 XP',html);self.assertIn('Citizen progression',html)
        self.assertNotIn('Enable citizen progression',html);self.assertNotIn('Enable citizen recovery',html)

    def test_health_and_morale_scale_work_xp(self):
        self.enable();self.sql('UPDATE citizens SET current_hp=50,morale=10 WHERE citizen_id=1')
        state=self.state();self.assertAlmostEqual(hourly_rates(state)[1],.35)
        self.sql('UPDATE citizens SET current_hp=0 WHERE citizen_id=1');self.assertNotIn(1,hourly_rates(self.state()))
    def test_crew_xp_matches_completed_work(self):
        self.enable();self.sql('DELETE FROM settlement_derelicts');self.sql('DELETE FROM season_derelicts')
        state=change_building(self.path,'build',building_type='garden',x=21,y=18,now=1000);bid=state['buildings'][-1]['building_id']
        for cid in (2,3):change_building(self.path,'builder',building_id=bid,citizen_id=cid,now=1000)
        state=self.run_to(1900)
        self.assertAlmostEqual(state['citizens'][1]['xp']+state['citizens'][2]['xp'],.5)
        self.assertAlmostEqual(state['citizens'][1]['xp'],.25)
    def test_suspension_and_season_finish_freeze_xp(self):
        self.enable();apply_action(self.path,'resume',now=1000)
        self.sql("UPDATE settlements SET status='suspended'");self.assertEqual(advance_settlement(self.path,now=1060)['citizens'][0]['xp'],0)
        self.sql("UPDATE settlements SET status='active'")
        self.sql('UPDATE seasons SET ends_at=1030,finalization_at=1000')
        state=advance_settlement(self.path,now=1060);self.assertAlmostEqual(state['citizens'][0]['xp'],30/3600)
        self.assertEqual(state,advance_settlement(self.path,now=2000))
    def test_converter_no_inputs_earns_no_xp(self):
        self.enable();bid=self.home('recycler');change_building(self.path,'worker',building_id=bid,citizen_id=2,now=1000)
        self.sql('UPDATE settlement_resources SET scrap=0')
        self.assertNotIn(2,hourly_rates(self.state()))
    def test_thresholds_match_read_only_workbook(self):
        from zipfile import ZipFile
        from xml.etree import ElementTree as ET
        from pathlib import Path
        config=load_config('prototype_v7');ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'};values={}
        with ZipFile(Path(__file__).resolve().parents[1]/'sources'/config['sources']['workbook']) as z:
            for name in z.namelist():
                if name.startswith('xl/worksheets/sheet') and name.endswith('.xml'):
                    for row in ET.fromstring(z.read(name)).findall('.//m:row',ns):
                        cells={''.join(filter(str.isalpha,c.get('r'))): ''.join(c.itertext()) if c.get('t')=='inlineStr' else c.findtext('m:v','',ns) for c in row}
                        if cells.get('A','').startswith(('xp_level_','productive_work_xp','construction_xp')):values[cells['A']]=float(cells['D'])
        self.assertEqual(config['progression']['thresholds'][1:],[values['xp_level_'+str(i)] for i in range(2,11)])
        self.assertEqual(config['progression']['work_xp_per_hour'],values['productive_work_xp'])
        self.assertEqual(config['progression']['construction_xp_per_hour'],2*values['construction_xp'])

import test_prototype as http_fixtures
from game.settlement import read_settlement
from urllib.parse import urlencode
class ProgressionHTTPTests(unittest.TestCase):
    setUp=http_fixtures.HTTPTests.setUp
    start_server=http_fixtures.HTTPTests.start_server
    stop_server=http_fixtures.HTTPTests.stop_server
    request=http_fixtures.HTTPTests.request
    create=http_fixtures.HTTPTests.create
    def test_activation_rejects_forged_requests_and_survives_restart(self):
        self.create();before=read_settlement(self.path)
        def post(token):return self.request('POST','/buildings',urlencode({'action':'enable_progression','token':token}),{'Content-Type':'application/x-www-form-urlencoded'})
        self.assertEqual(post('forged')[0],403);self.assertEqual(before,read_settlement(self.path))
        self.assertEqual(post(self.server.form_token)[0],303)
        status,_,html=self.request();self.assertEqual(status,200);self.assertIn('0.00 XP',html)
        saved=read_settlement(self.path);self.stop_server();self.start_server()
        self.assertEqual(saved,read_settlement(self.path));self.assertIn('Citizen progression',self.request()[2])

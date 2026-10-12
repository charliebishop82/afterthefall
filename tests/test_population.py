"""Housing, safe automatic allocation, and exactly-once survivor discovery."""
from contextlib import closing
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlencode
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from database.create_database import connect_database
from game.settlement import prepare_database, create_settlement, read_settlement, load_config
from game.buildings import change_building, spec
from game.simulation import apply_action, advance_settlement, resource_rates
from game.scavenging import assign
from game.population import housing, chance, rebalance
from game.views import render_page


class PopulationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/'population.db'
        prepare_database(self.path); create_settlement(self.path,'Housing',now=1000)
        seed = patch('game.scavenging.secrets.token_hex',return_value='housing-test-seed')
        seed.start(); self.addCleanup(seed.stop)

    def sql(self,query,values=()):
        with closing(connect_database(self.path)) as c,c:
            return c.execute(query,values).fetchall()

    def state(self): return read_settlement(self.path)
    def enable(self): return change_building(self.path,'enable_housing',now=1000)
    def fund(self): self.sql('UPDATE settlement_resources SET scrap=10000,metal=10000,electronics=10000')

    def home(self,kind='shack',level=1,hp=None,x=21,y=18):
        s=load_config('prototype_v5')['buildings'][kind]['levels'][level-1]
        return self.sql('''INSERT INTO buildings(settlement_id,building_type,level,origin_x,origin_y,current_hp,status,created_at,completed_at)
            VALUES (1,?,?,?,?,?,'active',1000,1000) RETURNING building_id''',
            (kind,level,x,y,s['hp'] if hp is None else hp))[0][0]

    def survivor(self,roll=0,fraction=.5):
        state=self.state(); d=state['derelicts'][0]; loot=json.loads(d['random_result'])
        loot['_survivor'].update(roll_pct=roll,at_fraction=fraction,resolved=False,name='Iris Wells',sex='female')
        self.sql('UPDATE settlement_derelicts SET random_result=? WHERE settlement_derelict_id=?',(json.dumps(loot),d['settlement_derelict_id']))
        assign(self.path,'assign',d['settlement_derelict_id'],2,now=1000)
        return d

    def test_enable_preserves_progress_loot_and_is_idempotent(self):
        change_building(self.path,'enable',now=1000)
        before=self.state(); state=self.enable()
        self.assertEqual(state['resources'],before['resources'])
        self.assertEqual(state['citizens'],before['citizens'])
        for old,new in zip(before['derelicts'],state['derelicts']):
            for r,v in json.loads(old['random_result']).items(): self.assertEqual(json.loads(new['random_result'])[r],v)
        self.assertEqual(state,change_building(self.path,'enable_housing',now=1000))
        self.assertEqual(state,change_building(self.path,'enable',now=1000))

    def test_housing_catalog_matches_source_workbook(self):
        config=load_config('prototype_v5'); ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with ZipFile(Path(__file__).resolve().parents[1]/'sources'/config['sources']['workbook']) as z:
            rows=[{''.join(filter(str.isalpha,a.get('r'))):''.join(a.itertext()) if a.get('t')=='inlineStr' else a.findtext('m:v','',ns) for a in row}
                  for row in ET.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//m:row',ns)]
        headers={v:k for k,v in rows[0].items()}
        fields={'minutes':'Build_Time_Min','hp':'HP','housing':'Housing_Capacity','morale_bonus':'Morale_Bonus',
                'scrap':'Scrap_Cost','metal':'Metal_Cost','electronics':'Electronics_Cost','oxygen_demand':'Oxygen_Demand'}
        for r in rows[1:]:
            if r.get('B')!='Housing':continue
            info=config['buildings'][r['A']]
            self.assertEqual(info['footprint'],list(map(int,r['E'].split('x'))))
            self.assertEqual(info['unlock'],int(r['D']))
            for level,s in enumerate(info['levels'],1):
                for key,field in fields.items():self.assertEqual(s[key],float(r.get(headers[f'{field}_L{level}']) or 0))

    def test_each_independent_housing_type_builds_and_upgrades(self):
        self.enable();self.fund()
        self.sql("UPDATE buildings SET level=3,current_hp=1900 WHERE building_id=1")
        self.sql("UPDATE settlement_derelicts SET status='cleared'")
        self.home('oxygen_garden',x=18,y=21)
        now=1000
        for kind,info in load_config('prototype_v5')['buildings'].items():
            if info['category']!='Housing':continue
            state=change_building(self.path,'build',building_type=kind,x=21,y=18,now=now)
            bid=state['buildings'][-1]['building_id']
            for level,s in enumerate(info['levels'],1):
                if level>1:state=change_building(self.path,'upgrade',building_id=bid,expected_level=level-1,now=now)
                state=change_building(self.path,'builder',building_id=bid,citizen_id=2,now=now)
                apply_action(self.path,'resume',now=now);now+=int(s['minutes']*60)
                state=advance_settlement(self.path,now=now)
                b=next(b for b in state['buildings'] if b['building_id']==bid)
                self.assertEqual((b['level'],b['status']),(level,'active'),(kind,level))
                self.assertEqual(state['citizens'][1]['assignment'],'unassigned')
                self.assertEqual(next(h for h in housing(state)['homes'] if h['building_id']==bid)['capacity'],int(s['housing']))
                apply_action(self.path,'pause',now=now)
            self.sql("UPDATE buildings SET status='demolished' WHERE building_id=?",(bid,))

    def test_invalid_build_rolls_back_enable_and_materials(self):
        before=self.state()
        with self.assertRaises(ValueError): change_building(self.path,'build',building_type='shack',x=18,y=18,now=1000)
        self.assertEqual(self.state(),before)

    def test_unlock_cost_staffing_and_stale_upgrade_rejected(self):
        self.enable();before=self.state()
        with self.assertRaises(ValueError):change_building(self.path,'build',building_type='house',x=21,y=18,now=1000)
        self.assertEqual(self.state(),before)
        bid=self.home('upgraded_tent')
        with self.assertRaises(ValueError):change_building(self.path,'worker',building_id=bid,citizen_id=2,now=1000)
        with self.assertRaises(ValueError):change_building(self.path,'upgrade',building_id=bid,expected_level=2,now=1000)
        self.sql('UPDATE settlement_resources SET scrap=0')
        before=self.state()
        with self.assertRaises(ValueError):change_building(self.path,'upgrade',building_id=bid,expected_level=1,now=1000)
        self.assertEqual(self.state(),before)

    def test_housing_condition_rounds_down_and_requires_oxygen(self):
        self.enable();bid=self.home(hp=89)
        self.assertEqual(housing(self.state())['capacity'],10)
        self.sql('UPDATE buildings SET current_hp=90 WHERE building_id=?',(bid,))
        self.assertEqual(housing(self.state())['capacity'],11)
        self.sql('UPDATE buildings SET origin_x=0,origin_y=0 WHERE building_id=?',(bid,))
        self.assertEqual(housing(self.state())['capacity'],10)

    def test_housing_oxygen_priority_and_electricity_optional(self):
        self.enable();bid=self.home('house',level=2)
        self.sql('UPDATE buildings SET current_hp=400 WHERE building_id=1') # 3.2 Oxygen, no usable House
        self.assertEqual(next(h for h in housing(self.state())['homes'] if h['building_id']==bid)['capacity'],0)
        self.sql('UPDATE buildings SET current_hp=1000 WHERE building_id=1')
        self.assertEqual(next(h for h in housing(self.state())['homes'] if h['building_id']==bid)['capacity'],5)
        # Housing uses no mandatory Electricity even if its optional coverage is unavailable.
        from game.economy import utilities
        self.assertEqual(utilities(self.state())['used']['electricity'],0)
        self.sql("UPDATE buildings SET status='upgrading' WHERE building_id=?",(bid,))
        self.assertEqual(next(h for h in housing(self.state())['homes'] if h['building_id']==bid)['capacity'],5)

    def test_best_housing_rank_and_seniority(self):
        self.enable();bid=self.home('house',level=2)
        self.sql('UPDATE citizens SET level=2,xp=9 WHERE citizen_id=6')
        self.sql('UPDATE citizens SET level=2,xp=10 WHERE citizen_id=5')
        assignments=housing(self.state())['assignments']
        self.assertEqual(assignments[5]['building_id'],bid)
        self.assertEqual(assignments[6]['building_id'],bid)
        self.assertEqual(assignments[4]['building_id'],1)
        self.sql('UPDATE citizen_settlement_history SET joined_at=2000 WHERE citizen_id=1')
        self.assertEqual(housing(self.state())['assignments'][1]['building_id'],1)

    def test_survivor_arrives_during_work_with_history_and_new_consumption(self):
        self.enable();d=self.survivor();apply_action(self.path,'resume',now=1000)
        boundary=1000+1350
        state=advance_settlement(self.path,now=boundary-1);self.assertEqual(len(state['citizens']),6)
        state=advance_settlement(self.path,now=boundary);self.assertEqual(len(state['citizens']),7)
        citizen=state['citizens'][-1]
        self.assertEqual((citizen['name'],citizen['sex'],citizen['level'],citizen['current_hp'],citizen['morale']),('Iris Wells','female',1,75,35))
        self.assertEqual(citizen['assignment'],'unassigned')
        self.assertEqual(resource_rates(state)['food']['consumption'],7)
        self.assertEqual(self.sql("SELECT arrival_reason FROM citizen_settlement_history WHERE citizen_id=?",(citizen['citizen_id'],)),[('scavenged_survivor',)])
        self.assertEqual(self.sql('SELECT level,xp_total FROM citizen_level_history WHERE citizen_id=?',(citizen['citizen_id'],)),[(1,0)])
        self.assertEqual(state['derelicts'][0]['status'],'scavenging')
        state=advance_settlement(self.path,now=boundary+100)
        self.assertEqual(len(state['citizens']),7)
        self.assertEqual(self.sql('PRAGMA foreign_key_check'),[])
        assigned=change_building(self.path,'build',building_type='garden',x=21,y=18,now=boundary+100)
        bid=assigned['buildings'][-1]['building_id']
        state=change_building(self.path,'builder',building_id=bid,citizen_id=citizen['citizen_id'],now=boundary+100)
        self.assertEqual(state['citizens'][-1]['assignment'],'construction')

    def test_population_decay_failure_and_no_rerolls(self):
        self.enable();d=self.survivor(roll=3)
        self.assertEqual(chance(self.state(),d),3)
        self.sql("INSERT INTO citizens(settlement_id,original_settlement_id,name,sex,current_hp,morale,status,created_at) VALUES (1,1,'Extra','male',100,60,'alive',1000)")
        self.assertEqual(chance(self.state(),d),2.75)
        apply_action(self.path,'resume',now=1000);state=advance_settlement(self.path,now=4000)
        self.assertEqual(len(state['citizens']),7)
        self.assertTrue(json.loads(state['derelicts'][0]['random_result'])['_survivor']['resolved'])
        self.assertEqual(len(advance_settlement(self.path,now=5000)['citizens']),7)

    def test_full_housing_survivor_joins_homeless_and_penalty_once(self):
        self.enable();self.sql('UPDATE buildings SET current_hp=600 WHERE building_id=1')
        self.survivor();apply_action(self.path,'resume',now=1000)
        state=advance_settlement(self.path,now=2350)
        self.assertEqual(len(state['citizens']),7)
        self.assertEqual(state['citizens'][-1]['morale'],25)
        self.assertEqual(state['citizens'][-1]['homeless_since'],2350)
        self.assertEqual(housing(state)['homeless'],1)
        state=advance_settlement(self.path,now=2450)
        self.assertEqual(state['citizens'][-1]['morale'],25)
        self.sql('UPDATE buildings SET current_hp=1000 WHERE building_id=1')
        state=advance_settlement(self.path,now=2500)
        self.assertIsNone(state['citizens'][-1]['homeless_since'])
        self.assertEqual(state['citizens'][-1]['morale'],25)

    def test_pause_and_removing_crew_stop_discovery(self):
        self.enable();self.survivor()
        self.assertEqual(len(advance_settlement(self.path,now=10000)['citizens']),6)
        apply_action(self.path,'resume',now=10000)
        assign(self.path,'release',1,2,now=10000)
        self.assertEqual(len(advance_settlement(self.path,now=12000)['citizens']),6)

    def test_offline_interval_matches_small_steps_after_population_change(self):
        self.enable();self.survivor();apply_action(self.path,'resume',now=1000)
        other=Path(self.temp.name)/'other.db'
        prepare_database(other)
        with closing(connect_database(self.path)) as c,closing(connect_database(other)) as d:c.backup(d)
        one=advance_settlement(self.path,now=4000)
        for at in range(1100,4001,100):many=advance_settlement(other,now=at)
        for r in ('food','water','scrap','metal','electronics'):self.assertAlmostEqual(one['resources'][r],many['resources'][r],places=7)
        self.assertEqual(one['citizens'],many['citizens'])

    def test_survivor_failure_rolls_back_progress_loot_and_creation(self):
        self.enable();self.survivor();apply_action(self.path,'resume',now=1000)
        self.sql("CREATE TRIGGER reject_survivor BEFORE INSERT ON citizen_settlement_history WHEN NEW.arrival_reason='scavenged_survivor' BEGIN SELECT RAISE(ABORT,'fixture'); END")
        before=self.state()
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):advance_settlement(self.path,now=2350)
        self.assertEqual(before,self.state())

    def test_completed_ruins_not_retroactive_and_private_data_not_in_ui(self):
        change_building(self.path,'enable',now=1000)
        self.sql("UPDATE settlement_derelicts SET status='cleared' WHERE settlement_derelict_id=1")
        state=self.enable()
        self.assertNotIn('_survivor',json.loads(state['derelicts'][0]['random_result']))
        page=render_page(state,'test-token').decode()
        for secret in ('roll_pct','at_fraction','random_nonce','housing-test-seed'):
            self.assertNotIn(secret,page)
        self.assertIn('usable housing places',page)
        for label in ('Pup Tent','Upgraded Tent','Shack','House','Apartment Block'):self.assertIn(label,page)

    def test_oxygen_loss_evacuates_and_restore_rehouses_without_repeated_penalty(self):
        self.enable()
        self.sql('UPDATE buildings SET current_hp=300 WHERE building_id=1')
        apply_action(self.path,'resume',now=1000)
        state=advance_settlement(self.path,now=1001)
        self.assertEqual(housing(state)['homeless'],3)
        self.assertEqual([c['morale'] for c in state['citizens']],[60,60,60,50,50,50])
        state=advance_settlement(self.path,now=1002)
        self.assertEqual([c['morale'] for c in state['citizens']],[60,60,60,50,50,50])
        self.sql('UPDATE buildings SET current_hp=1000 WHERE building_id=1')
        state=advance_settlement(self.path,now=1003)
        self.assertEqual(housing(state)['homeless'],0)
        self.assertTrue(all(c['homeless_since'] is None for c in state['citizens']))


class PopulationHTTPTests(unittest.TestCase):
    # Reuse the established disposable HTTP harness without inheriting old tests.
    import test_prototype as earlier
    setUp=earlier.HTTPTests.setUp
    start_server=earlier.HTTPTests.start_server
    stop_server=earlier.HTTPTests.stop_server
    request=earlier.HTTPTests.request
    create=earlier.HTTPTests.create

    def test_enable_housing_forms_and_rejected_commands(self):
        self.create()
        before=read_settlement(self.path)
        def post(fields):
            return self.request('POST','/buildings',urlencode(fields),{'Content-Type':'application/x-www-form-urlencoded'})
        self.assertEqual(post({'action':'enable_housing','token':'forged'})[0],403)
        self.assertEqual(before,read_settlement(self.path))
        self.assertEqual(post({'action':'enable_housing','token':self.server.form_token})[0],303)
        status,_,page=self.request()
        self.assertEqual(status,200)
        self.assertIn('6 citizens / 10 usable housing places',page)
        self.assertIn('Pup Tent',page)
        before=read_settlement(self.path)
        self.assertEqual(post({'action':'build','building_type':'shack','x':18,'y':18,'token':self.server.form_token})[0],400)
        self.assertEqual(before,read_settlement(self.path))
        api=self.request(path='/api/resources')[2]
        for secret in ('roll_pct','at_fraction','random_nonce'):self.assertNotIn(secret,api)


if __name__=='__main__':unittest.main()

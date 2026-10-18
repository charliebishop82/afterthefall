"""Military production, persisted batches and storage/ownership boundaries."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from database.create_database import connect_database
from game import accounts,manufacturing
from game.buildings import change_building,spec
from game.settlement import account_scope,read_settlement,load_config
from game.simulation import advance_settlement
from tests.fixtures import baseline_world


class ManufacturingTests(unittest.TestCase):
    def setUp(self):
        world=baseline_world(self,'manufacturing',manufacturing_baseline)
        self.__dict__.update({k:v for k,v in vars(world).items() if k not in ('addCleanup','_testMethodName','_testMethodDoc','_outcome','_cleanups','_subtest','_type_equality_funcs')})

    def prepare_world(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'military.db';accounts.prepare(self.path)
        self.a=self.sql("INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES ('alpha','!','alpha',1000) RETURNING account_id")[0][0]
        self.sid=accounts.join(self.path,self.a,'Alpha',1000)
        self.sql('DELETE FROM settlement_derelicts');self.sql('DELETE FROM season_derelicts')
        self.action('enable')
        definition=load_config('prototype_v9')['buildings']['town_hall']['levels'][2]
        self.sql('UPDATE buildings SET level=3,current_hp=? WHERE building_type=\'town_hall\'',(definition['hp'],))
        self.sql('UPDATE settlement_resources SET metal=150,electronics=100')
        self.factory=self.build_fixture('drone_factory',21,18)
        self.home=self.build_fixture('offensive_hangar',18,21)
        self.build_fixture('wind_turbine',21,15,level=3)
        self.worker=self.state()['citizens'][1]['citizen_id']
        self.sql("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,building_id,assigned_at) VALUES (?,1,'production',?,1000)",(self.worker,self.factory))
        self.sql('UPDATE citizens SET unemployed_since=NULL WHERE citizen_id=?',(self.worker,))
    def sql(self,query,args=()):
        with closing(connect_database(self.path)) as c,c:return c.execute(query,args).fetchall()
    def state(self):
        with account_scope(self.a):return read_settlement(self.path)
    def action(self,action,now=1000,**args):
        with account_scope(self.a):return manufacturing.command(self.path,action,now,**args)
    def advance(self,now):
        with account_scope(self.a):return advance_settlement(self.path,now)
    def build_fixture(self,kind,x,y,level=1):
        hp=load_config('prototype_v9')['buildings'][kind]['levels'][level-1]['hp']
        return self.sql("INSERT INTO buildings(settlement_id,building_type,level,origin_x,origin_y,current_hp,status,created_at,completed_at) VALUES (1,?,?,?,?,?,'active',1000,1000) RETURNING building_id",(kind,level,x,y,hp))[0][0]
    def queue(self,unit='offensive_drone',quantity=1,repeat=False,now=1000,factory=None):
        self.action('queue',now,building_id=factory or self.factory,unit_type=unit,quantity=quantity,repeat=repeat)
        return self.state()['jobs'][-1]['job_id']
    def test_source_units_cost_times_hp_and_storage_capacities(self):
        ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        workbook=Path(__file__).resolve().parents[1]/'sources/Post_Apocalyptic_Game_V1_Building_Settings(1).xlsx'
        found={}
        with ZipFile(workbook) as z:
            for i,sheet in enumerate(ET.fromstring(z.read('xl/workbook.xml')).findall('.//s:sheet',ns),1):
                if sheet.attrib['name'] not in ('Manufactured Units','Buildings'):continue
                rows=[]
                for row in ET.fromstring(z.read(f'xl/worksheets/sheet{i}.xml')).findall('.//s:row',ns):
                    rows.append({''.join(filter(str.isalpha,c.attrib['r'])):''.join(c.find('s:is',ns).itertext()) if c.get('t')=='inlineStr' else c.findtext('s:v','',ns) for c in row})
                found[sheet.attrib['name']]=rows
        config=load_config('prototype_v9')
        for row in found['Manufactured Units'][1:]:
            unit=config['units'][row['A']]
            self.assertEqual((unit['metal'],unit['electronics'],unit['seconds'],unit['hp']),(float(row['D']),float(row['E']),float(row['F'])*60,float(row['H'])))
        header=found['Buildings'][0]
        for raw in found['Buildings'][1:]:
            if raw.get('A') not in ('drone_factory','munitions_factory','offensive_hangar','air_defense_bay','ground_defense_bay','engineering_workshop','missile_silo','interceptor_battery'):continue
            row={header[k]:v for k,v in raw.items()};building=config['buildings'][row['Building_ID']]
            self.assertEqual(building['unlock'],int(row['Town_Hall_Unlock']))
            for i,level in enumerate(building['levels'],1):
                for key,column in {'workers':'Workers_Max','minutes':'Build_Time_Min','hp':'HP','scrap':'Scrap_Cost','metal':'Metal_Cost','electronics':'Electronics_Cost','drone_capacity':'Drone_Capacity','repair_drone_capacity':'Repair_Drone_Capacity','munition_capacity':'Munition_Capacity','production_bonus':'Production_Speed_Bonus_Pct','electricity_demand':'Electricity_Demand','oxygen_demand':'Oxygen_Demand'}.items():
                    self.assertEqual(level[key],float(row[f'{column}_L{i}']))
    def test_drone_pays_once_completes_at_boundary_and_persists(self):
        self.queue();state=self.state()
        self.assertEqual(state['resources']['metal'],132);self.assertEqual(state['resources']['electronics'],94)
        state=self.advance(2799);self.assertEqual(state['units'],[])
        state=self.advance(2800);self.assertEqual(len(state['units']),1)
        unit=state['units'][0];self.assertEqual((unit['unit_type'],unit['current_hp'],unit['home_building_id']),('offensive_drone',100,self.home))
        self.assertEqual(state,self.advance(2800));self.assertEqual(state,self.state())
    def test_batches_and_queue_are_sequential_and_repeat_can_stop(self):
        first=self.queue(quantity=2);second=self.queue()
        self.assertEqual(self.state()['jobs'][1]['status'],'queued')
        state=self.advance(6400);self.assertEqual(len(state['units']),3)
        self.assertTrue(all(j['status']=='completed' for j in state['jobs']))
        third=self.queue(repeat=True,now=6400)
        state=self.advance(8200);self.assertEqual(len(state['units']),4)
        self.action('stop',8200,job_id=third);state=self.advance(10000)
        self.assertEqual(len(state['units']),5);self.assertEqual(state['jobs'][-1]['status'],'completed')
    def test_storage_full_pauses_without_spending_or_wasting_then_upgrade_resumes(self):
        for _ in range(6):self.sql("INSERT INTO military_units(settlement_id,unit_type,current_hp,home_building_id,status,created_at) VALUES (1,'offensive_drone',100,?,'available',1000)",(self.home,))
        self.queue();before=self.state()['resources']['metal'];state=self.advance(1600)
        self.assertEqual(state['jobs'][0]['work_completed'],0);self.assertEqual(state['resources']['metal'],before)
        self.assertIn('storage',state['jobs'][0]['pause_reason'])
        hp=load_config('prototype_v9')['buildings']['offensive_hangar']['levels'][1]['hp']
        self.sql('UPDATE buildings SET level=2,current_hp=? WHERE building_id=?',(hp,self.home))
        state=self.advance(3400);self.assertEqual(len(state['units']),7)
    def test_power_loss_pauses_paid_unit_and_resumes_without_double_spend(self):
        self.queue();self.sql('UPDATE buildings SET origin_x=35,origin_y=35 WHERE building_id=?',(self.home,))
        state=self.advance(1600);self.assertEqual(state['jobs'][0]['work_completed'],0);self.assertEqual(state['resources']['metal'],132)
        self.sql('UPDATE buildings SET origin_x=18,origin_y=21 WHERE building_id=?',(self.home,))
        state=self.advance(3400);self.assertEqual(len(state['units']),1);self.assertEqual(state['resources']['metal'],132)
    def test_missing_workers_and_materials_pause_and_no_stalled_xp(self):
        self.sql('UPDATE settlement_resources SET electronics=0');self.queue()
        state=self.advance(1600);self.assertEqual(state['jobs'][0]['work_completed'],0)
        self.assertEqual(next(c for c in state['citizens'] if c['citizen_id']==self.worker)['xp'],0)
        self.sql('UPDATE settlement_resources SET electronics=6')
        self.sql("UPDATE citizen_assignments SET ended_at=1600,end_reason='test_fixture' WHERE citizen_id=?",(self.worker,))
        state=self.advance(2200);self.assertEqual(state['resources']['electronics'],6)
        self.sql("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,building_id,assigned_at) VALUES (?,1,'production',?,2200)",(self.worker,self.factory))
        state=self.advance(4000);self.assertEqual(len(state['units']),1)
    def test_wrong_storage_foreign_ids_invalid_units_and_fractional_batches_rejected(self):
        before=self.state()
        for args in ({'building_id':999,'unit_type':'offensive_drone'},{'building_id':self.factory,'unit_type':'missile'},{'building_id':self.factory,'unit_type':'invalid'},{'building_id':self.factory,'unit_type':'offensive_drone','quantity':1.5}):
            with self.assertRaises(ValueError):self.action('queue',**args)
        self.assertEqual(before,self.state())
        self.sql("UPDATE buildings SET building_type='air_defense_bay' WHERE building_id=?",(self.home,))
        self.queue();self.assertIn('storage',self.state()['jobs'][0]['pause_reason'])
    def test_level_speed_bonus_and_multiple_workers(self):
        hp=load_config('prototype_v9')['buildings']['drone_factory']['levels'][1]['hp']
        self.sql('UPDATE buildings SET level=2,current_hp=? WHERE building_id=?',(hp,self.factory))
        citizen=self.state()['citizens'][2]['citizen_id']
        self.sql("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,building_id,assigned_at) VALUES (?,1,'production',?,1000)",(citizen,self.factory))
        self.queue();state=self.advance(1783)
        self.assertEqual(len(state['units']),1)
    def test_missiles_and_interceptors_use_inventory_and_their_own_storage(self):
        self.sql("UPDATE citizen_assignments SET ended_at=1000,end_reason='test_fixture' WHERE citizen_id=?",(self.worker,))
        factory=self.build_fixture('munitions_factory',21,21)
        silo=self.build_fixture('missile_silo',16,21)
        battery=self.build_fixture('interceptor_battery',16,16)
        self.sql("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,building_id,assigned_at) VALUES (?,1,'production',?,1000)",(self.worker,factory))
        # Unstaffed drone factory uses no power, leaving room for both stores.
        self.queue('missile',factory=factory);self.queue('interceptor',factory=factory)
        state=self.advance(4300)
        self.assertEqual({i['unit_type']:i['quantity'] for i in state['inventory']},{'missile':1,'interceptor':1})
        self.assertEqual(state['units'],[])
        self.assertEqual({i['building_id'] for i in state['inventory']},{silo,battery})
    def test_cancel_unfunded_queue_and_refuse_paid_cancel(self):
        first=self.queue();second=self.queue()
        with self.assertRaises(ValueError):self.action('cancel',job_id=first)
        self.action('cancel',job_id=second)
        self.assertEqual(self.state()['jobs'][1]['status'],'cancelled')
    def test_final_window_blocks_new_batches_stops_repeat_and_end_cancels_queue(self):
        self.queue(repeat=True);self.queue()
        self.sql('UPDATE seasons SET finalization_at=2000,ends_at=2900')
        with self.assertRaises(ValueError):self.queue(now=2000)
        state=self.advance(2900)
        self.assertEqual(len(state['units']),1)
        self.assertEqual(state['season']['status'],'finished')
        self.assertEqual(state['jobs'][0]['status'],'completed');self.assertEqual(state['jobs'][1]['status'],'cancelled')
    def test_offline_and_small_steps_identical(self):
        self.queue(quantity=2)
        other=Path(self.tmp.name)/'copy.db'
        with closing(connect_database(self.path)) as a,closing(sqlite3.connect(other)) as b:a.backup(b)
        long=self.advance(4600)
        for now in range(1060,4601,60):
            with account_scope(self.a):short=advance_settlement(other,now)
        self.assertEqual(long,short)
    def test_late_join_preserves_v9_catalog_and_existing_manufacturing(self):
        self.queue();before=self.state()
        b=self.sql("INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES ('bravo','!','bravo',1000) RETURNING account_id")[0][0]
        accounts.join(self.path,b,'Bravo',1000)
        self.assertEqual(self.state(),before)

    def test_all_defense_and_repair_drone_types_use_matching_storage(self):
        now=1000
        for kind in ('air_defense_drone','ground_defense_drone','repair_drone'):
            unit=load_config('prototype_v9')['units'][kind]
            home=self.build_fixture(unit['storage'],15,18)
            if kind=='repair_drone':
                worker=self.state()['citizens'][2]['citizen_id']
                self.sql("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,building_id,assigned_at) VALUES (?,1,'production',?,?)",(worker,home,now))
            self.queue(kind,now=now);now+=int(unit['seconds'])
            state=self.advance(now)
            produced=next(u for u in state['units'] if u['unit_type']==kind)
            self.assertEqual((produced['current_hp'],produced['home_building_id']),(unit['hp'],home))

    def test_two_factories_cannot_reserve_the_same_last_slot(self):
        for _ in range(5):self.sql("INSERT INTO military_units(settlement_id,unit_type,current_hp,home_building_id,status,created_at) VALUES (1,'offensive_drone',100,?,'available',1000)",(self.home,))
        other=self.build_fixture('drone_factory',21,21)
        worker=self.state()['citizens'][2]['citizen_id']
        self.sql("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,building_id,assigned_at) VALUES (?,1,'production',?,1000)",(worker,other))
        self.queue();self.queue(factory=other)
        self.assertEqual(self.state()['resources']['metal'],132)
        state=self.advance(2800)
        self.assertEqual(len(state['units']),6)
        self.assertEqual(state['jobs'][1]['work_completed'],0)

    def test_trading_reservations_cannot_fund_manufacturing(self):
        b=self.sql("INSERT INTO accounts(username,password_hash,display_name,created_at) VALUES ('bravo','!','bravo',1000) RETURNING account_id")[0][0]
        sid=accounts.join(self.path,b,'Bravo',1000)
        tid=self.sql("INSERT INTO trade_proposals(season_id,proposer_settlement_id,recipient_settlement_id,status,proposed_at,expires_at) VALUES (1,1,?,'pending',1000,87400) RETURNING trade_id",(sid,))[0][0]
        self.sql("INSERT INTO resource_reservations(settlement_id,resource_type,quantity,trade_proposal_id,created_at) VALUES (1,'metal',150,?,1000)",(tid,))
        self.queue();state=self.advance(1600)
        self.assertEqual(state['resources']['metal'],150)
        self.assertEqual(state['jobs'][0]['work_completed'],0)
        self.assertEqual(state['jobs'][0]['pause_reason'],'Waiting for materials')

    def test_materials_arriving_offline_start_production_at_input_boundary(self):
        self.sql('UPDATE settlement_resources SET metal=0')
        recycler=self.build_fixture('recycler',15,18)
        worker=self.state()['citizens'][2]['citizen_id']
        self.sql("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,building_id,assigned_at) VALUES (?,1,'production',?,1000)",(worker,recycler))
        self.queue()
        other=Path(self.tmp.name)/'arrivals.db'
        with closing(connect_database(self.path)) as a,closing(sqlite3.connect(other)) as b:a.backup(b)
        long=self.advance(13000)
        for now in range(1060,13001,60):
            with account_scope(self.a):short=advance_settlement(other,now)
        self.assertEqual(long,short)
        self.assertEqual(len(long['units']),1)

    def test_manufacturing_job_cannot_accept_construction_assignment(self):
        self.queue()
        citizen=self.state()['citizens'][2]['citizen_id']
        before=self.state()
        with account_scope(self.a):
            with self.assertRaises(ValueError):change_building(self.path,'builder',building_id=self.factory,citizen_id=citizen,now=1000)
        self.assertEqual(before,self.state())

    def test_factory_constructs_and_upgrades_with_existing_builder_controls(self):
        with account_scope(self.a):
            state=change_building(self.path,'build',building_type='drone_factory',x=15,y=15,now=1000)
        bid=state['buildings'][-1]['building_id'];citizen=state['citizens'][2]['citizen_id']
        self.assertEqual(state['resources']['metal'],10)
        with account_scope(self.a):change_building(self.path,'builder',building_id=bid,citizen_id=citizen,now=1000)
        state=self.advance(8200)
        factory=next(b for b in state['buildings'] if b['building_id']==bid)
        self.assertEqual((factory['status'],factory['level'],factory['current_hp']),('active',1,900))
        self.sql('UPDATE settlement_resources SET scrap=500,metal=500,electronics=100')
        with account_scope(self.a):
            change_building(self.path,'upgrade',building_id=bid,expected_level=1,now=8200)
            change_building(self.path,'builder',building_id=bid,citizen_id=citizen,now=8200)
        state=self.advance(18100)
        factory=next(b for b in state['buildings'] if b['building_id']==bid)
        self.assertEqual((factory['status'],factory['level'],factory['current_hp']),('active',2,1200))


def manufacturing_baseline(owner):
    world=ManufacturingTests('test_offline_and_small_steps_identical')
    world.addCleanup=owner.addCleanup
    world.prepare_world()
    return world

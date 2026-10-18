"""Disposable guard, support and finite drone combat integration scenarios."""
from contextlib import closing
import json,sqlite3,tempfile,unittest,shutil
from pathlib import Path
from database.create_database import connect_database
from game import accounts,combat,support,drones,manufacturing
from game.buildings import change_building,spec,job_speed
from game.settlement import account_scope,read_settlement,load_config
from game.simulation import advance_settlement

from tests.fixtures import SupportFixture,SupportWorld,baseline_world

class DefenseSupportTests(SupportFixture, unittest.TestCase):
 def setUp(self):
  world=baseline_world(self,'support',SupportWorld)
  self.__dict__.update({k:v for k,v in vars(world).items() if k!='addCleanup'})

 def test_activation_idempotent_and_late_join_preserves_all_versions(self):
  before=self.state();self.change('enable_support');self.assertEqual(before,self.state())
  _,sid=self.player('charlie');self.assertEqual(self.state()['season']['config_version'],'prototype_v10');self.assertEqual(sid,3)
  self.assertIsNone(self.state()['needs_clock'])
 def test_catalog_unlocks_and_all_support_costs_from_workbook(self):
  import zipfile,xml.etree.ElementTree as E,re
  n={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
  with zipfile.ZipFile(Path(__file__).resolve().parents[1]/'sources/Post_Apocalyptic_Game_V1_Building_Settings(1).xlsx') as z:
   rows=[]
   for r in E.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//s:row',n):
    rows.append({re.sub(r'\d+$','',c.attrib['r']):''.join(c.find('s:is',n).itertext()) if c.get('t')=='inlineStr' else c.findtext('s:v','',n) for c in r})
  h=rows[0]
  for row in rows[1:]:
   if row.get('A') not in ('guard_post','clinic','medical_center','engineering_workshop','salvage_depot','trading_post','community_center'):continue
   raw={h[k]:v for k,v in row.items()};info=self.config['buildings'][row['A']]
   self.assertEqual(info['unlock'],int(raw['Town_Hall_Unlock']))
   for i,s in enumerate(info['levels'],1):
    for k,col in {'hp':'HP','workers':'Workers_Max','minutes':'Build_Time_Min','scrap':'Scrap_Cost','metal':'Metal_Cost','electronics':'Electronics_Cost','healing_bonus':'Healing_Bonus_Pct','construction_bonus':'Construction_Repair_Bonus_Pct','scavenge_bonus':'Scavenge_Speed_Bonus_Pct','salvage_bonus':'Salvage_Yield_Bonus_Pct','defense_radius':'Defense_Radius_Tiles','defense_strength':'Defense_Strength'}.items():self.assertEqual(s[k],float(raw[f'{col}_L{i}']))
 def test_guard_patrol_exclusive_owned_capacity_and_repeat(self):
  p=self.build('guard_post');ids=[c['citizen_id'] for c in self.state()['citizens'][1:]]
  self.change('guard',building_id=p,citizen_id=ids[0]);self.change('guard',building_id=p,citizen_id=ids[0])
  self.assertEqual(len(self.sql('SELECT * FROM citizen_assignments WHERE citizen_id=? AND ended_at IS NULL',(ids[0],))),1)
  for action,args in [('guard',{'building_id':p,'citizen_id':ids[1]}),('patrol',{'citizen_id':ids[0]}),('worker',{'building_id':p,'citizen_id':ids[1]})]:
   with self.assertRaises(ValueError):self.change(action,**args)
  with self.assertRaises(ValueError):self.change('guard',account=self.b,building_id=p,citizen_id=self.state(self.b)['citizens'][1]['citizen_id'])
  self.change('release_defense',citizen_id=ids[0]);self.change('patrol',citizen_id=ids[0]);self.change('patrol',citizen_id=ids[0])
  self.assertEqual(self.state()['citizens'][1]['assignment'],'patrol')
 def test_guard_readiness_radius_oxygen_condition_and_upgrade(self):
  p=self.build('guard_post');cid=self.state()['citizens'][1]['citizen_id'];self.change('guard',building_id=p,citizen_id=cid)
  state=self.state();self.assertEqual(len(support.guards(state)),1);self.assertGreater(support.defense_bonus(state),0)
  self.sql('UPDATE buildings SET origin_x=35,origin_y=35 WHERE building_id=?',(p,));self.assertEqual(support.guards(self.state()),[])
  self.sql("UPDATE buildings SET origin_x=21,origin_y=18,status='upgrading' WHERE building_id=?",(p,));self.assertEqual(support.guards(self.state()),[])
  self.sql("UPDATE buildings SET status='active',current_hp=1 WHERE building_id=?",(p,));self.assertEqual(support.guards(self.state()),[])
 def test_community_is_current_nonstacking_and_power_optional(self):
  p=self.build('community_center');self.staff(p,2);state=self.state();bonus=support.community(state)
  self.assertAlmostEqual(bonus,3.75);self.assertAlmostEqual(state['citizens'][0]['effective_morale'],63.75)
  q=self.build('community_center',x=18,y=21);self.staff(q,2);self.assertAlmostEqual(support.community(self.state()),bonus)
  self.sql("UPDATE buildings SET current_hp=0 WHERE building_type='wind_turbine'");self.sql("UPDATE buildings SET current_hp=0 WHERE building_type='town_hall'")
  self.assertEqual(support.community(self.state()),0)
  self.sql("UPDATE buildings SET current_hp=? WHERE building_type='town_hall'",(self.config['buildings']['town_hall']['levels'][2]['hp'],))
  for cid in [c['citizen_id'] for c in self.state()['citizens'] if c['building_id'] in (p,q)]:self.change('release',building_id=next(c['building_id'] for c in self.state()['citizens'] if c['citizen_id']==cid),citizen_id=cid)
  self.assertEqual(self.state()['citizens'][0]['effective_morale'],60)
 def test_medical_capacity_most_injured_condition_and_no_duplicate_stack(self):
  p=self.build('clinic');self.staff(p,2);ids=[c['citizen_id'] for c in self.state()['citizens']]
  for cid,hp in zip(ids,[90,80,70,60,50,40]):self.sql('UPDATE citizens SET current_hp=? WHERE citizen_id=?',(hp,cid))
  care=support.treatment(self.state());self.assertLessEqual(len(care),2);self.assertIn(ids[-1],care)
  q=self.build('clinic',x=18,y=21);self.staff(q,2)
  self.assertLessEqual(len(support.treatment(self.state())),2)
  before={c['citizen_id']:c['current_hp'] for c in self.state()['citizens']};state=self.advance(1060)
  self.assertGreater(state['citizens'][-1]['current_hp']-before[ids[-1]],2/60)
  self.assertAlmostEqual(state['citizens'][0]['current_hp']-before[ids[0]],2/60)
 def test_clinic_works_without_power_medical_center_needs_power(self):
  p=self.build('clinic');self.staff(p,2);cid=self.state()['citizens'][-1]['citizen_id'];self.sql('UPDATE citizens SET current_hp=50 WHERE citizen_id=?',(cid,))
  self.assertTrue(support.treatment(self.state()));self.sql("UPDATE buildings SET current_hp=0 WHERE building_type='wind_turbine'")
  self.assertTrue(support.treatment(self.state()))
  self.sql("UPDATE buildings SET building_type='medical_center',level=3,current_hp=? WHERE building_id=?",(self.config['buildings']['medical_center']['levels'][2]['hp'],p))
  self.sql("UPDATE buildings SET level=1,current_hp=1000 WHERE building_type='town_hall'")
  self.assertEqual(support.treatment(self.state()),{})
 def test_engineering_bonus_staff_condition_and_no_stack(self):
  p=self.build('engineering_workshop');self.staff(p,2);self.assertAlmostEqual(support.best(self.state(),'construction_bonus'),10)
  q=self.build('engineering_workshop',x=18,y=21);self.staff(q,2);self.assertAlmostEqual(support.best(self.state(),'construction_bonus'),10)
  self.sql('UPDATE buildings SET current_hp=current_hp/2 WHERE building_id IN (?,?)',(p,q));self.assertAlmostEqual(support.best(self.state(),'construction_bonus'),5)
 def test_salvage_live_speed_and_material_yield_only(self):
  from game.scavenging import speed,progress
  from game.economy import rates
  p=self.build('salvage_depot');self.staff(p,2)
  common=self.sql("INSERT INTO season_derelicts(season_id,derelict_type,origin_x,origin_y) VALUES (1,'abandoned_house',18,21) RETURNING season_derelict_id")[0][0]
  kind=next(iter(self.config['derelicts']));self.sql('UPDATE season_derelicts SET derelict_type=?',(kind,))
  d=self.sql("INSERT INTO settlement_derelicts(settlement_id,season_id,season_derelict_id,status,random_key_ref,random_nonce,random_result,created_at) VALUES (?,1,?,'scavenging','test','nonce',?,1000) RETURNING settlement_derelict_id",(self.sa,common,json.dumps(dict.fromkeys(('food','water','scrap','metal','electronics'),10))))[0][0]
  j=self.sql("INSERT INTO settlement_jobs(settlement_id,job_type,target_type,target_derelict_id,work_required,status,created_at,last_processed_at) VALUES (?,'scavenging','derelict',?,3600,'active',1000,1000) RETURNING job_id",(self.sa,d))[0][0]
  cid=self.state()['citizens'][-1]['citizen_id'];self.sql("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,job_id,assigned_at) VALUES (?,?,'scavenging',?,1000)",(cid,self.sa,j))
  state=self.state();job=state['jobs'][0];self.assertAlmostEqual(speed(state,job),1.15)
  flow=rates(state);self.assertAlmostEqual(flow['scrap']['production'],10*1.15*1.05)
  state=self.advance(1060);recovered=json.loads(state['derelicts'][0]['recovered_loot']);self.assertAlmostEqual(recovered['scrap']/recovered['food'],1.05)
 def test_support_offline_matches_small_steps_and_pause(self):
  p=self.build('clinic');self.staff(p,2);self.sql('UPDATE citizens SET current_hp=70')
  clone=self.path.with_name('clone.db');shutil.copy2(self.path,clone)
  one=self.advance(1600);original=self.path;self.path=clone
  for t in range(1060,1601,60):two=self.advance(t)
  self.path=original
  self.assertEqual([(c['current_hp'],c['xp']) for c in one['citizens']],[(c['current_hp'],c['xp']) for c in two['citizens']])
 def test_drone_only_raid_spends_allowance_returns_hp_loot_and_idempotent(self):
  self.weak();uid=self.unit();aid=self.raid(units=[uid]);self.assertEqual(self.state()['units'][0]['status'],'deployed');self.assertEqual(self.state()['settlement']['attacks_remaining'],2)
  with self.assertRaises(ValueError):self.raid(units=[uid],now=4600)
  self.advance(8200);report=self.report();self.assertEqual(report['result'],'attacker_win');self.assertAlmostEqual(sum(report['loot']['taken'].values()),20)
  self.assertEqual(self.state()['units'][0]['current_hp'],90);self.assertEqual(self.state()['units'][0]['status'],'available')
  self.advance(8200);self.assertEqual(len(self.sql('SELECT * FROM battle_reports')),2)
 def test_mixed_raid_combines_surviving_capacity(self):
  self.weak();cid=self.extra()[0];uid=self.unit();self.raid(citizens=[cid],units=[uid]);self.advance(8200)
  self.assertAlmostEqual(sum(self.report()['loot']['taken'].values()),32)
 def test_air_first_then_ground_only_for_citizens(self):
  self.weak();uid=self.unit();air=self.unit('air_defense_drone',sid=self.sb);ground=self.unit('ground_defense_drone',sid=self.sb)
  self.raid(units=[uid]);self.advance(8200);report=self.report()
  self.assertIsNotNone(report['air_battle']['result']);self.assertEqual(len(report['air_battle']['defenders']),1);self.assertEqual(report['ground_drones'],[])
  self.assertEqual(self.sql('SELECT current_hp FROM military_units WHERE unit_id=?',(ground,))[0][0],120)
  self.assertLess(self.sql('SELECT current_hp FROM military_units WHERE unit_id=?',(air,))[0][0],100)
 def test_ground_drones_join_citizen_raids_air_drones_do_not(self):
  ground=self.unit('ground_defense_drone',sid=self.sb);air=self.unit('air_defense_drone',sid=self.sb);cid=self.extra()[0]
  self.raid(citizens=[cid]);self.advance(8200);report=self.report();self.assertEqual(len(report['ground_drones']),1);self.assertIsNone(report['air_battle']['result'])
  self.assertEqual(self.sql('SELECT current_hp FROM military_units WHERE unit_id=?',(air,))[0][0],100)
 def test_destroyed_drone_cannot_loot_and_frees_slot(self):
  self.weak();uid=self.unit(hp=5);self.raid(units=[uid]);self.advance(8200)
  self.assertEqual(self.state()['units'][0]['status'],'destroyed');self.assertEqual(sum(self.report()['loot']['taken'].values()),0)
  self.assertEqual(manufacturing.occupancy(self.state(),self.state()['units'][0]['home_building_id']),0)
 def test_foreign_duplicate_wrong_type_unpowered_and_repairing_rejected(self):
  own=self.unit();foreign=self.unit(sid=self.sb);repair=self.unit('repair_drone')
  with account_scope(self.a):combat.command(self.path,'declare',1000,target_id=self.sb)
  for ids in ([own,own],[foreign],[repair]):
   with self.assertRaises(ValueError):self.raid(units=ids)
  self.sql("UPDATE military_units SET status='repairing' WHERE unit_id=?",(own,))
  with self.assertRaises(ValueError):self.raid(units=[own])
  self.sql("UPDATE military_units SET status='available' WHERE unit_id=?",(own,));self.sql("UPDATE buildings SET status='upgrading' WHERE building_type='offensive_hangar' AND settlement_id=?",(self.sa,))
  with self.assertRaises(ValueError):self.raid(units=[own])
  self.assertEqual(self.sql('SELECT count(*) FROM attacks')[0][0],0);self.assertEqual(self.state()['settlement']['attacks_remaining'],3)
 def test_system_recall_returns_drones_and_refunds_once(self):
  uid=self.unit();self.raid(units=[uid]);self.sql('UPDATE settlements SET protection_until=9000 WHERE settlement_id=?',(self.sb,));self.advance(8200)
  self.assertEqual(self.state()['units'][0]['status'],'available');self.assertEqual(self.state()['settlement']['attacks_remaining'],3)
  self.advance(8201);self.assertEqual(self.state()['settlement']['attacks_remaining'],3)
 def test_drone_strength_hp_floor_and_no_citizen_identity(self):
  uid=self.unit(hp=1);u=self.state()['units'][0];self.assertEqual(drones.strength(self.state(),u),6)
  self.assertEqual(len(self.state()['citizens']),6)
 def test_guard_and_patrol_contribute_to_resolved_strength(self):
  self.weak();self.sql("DELETE FROM citizen_assignments WHERE settlement_id=? AND assignment_type='production'",(self.sb,))
  p=self.build('guard_post',sid=self.sb);ids=[c['citizen_id'] for c in self.state(self.b)['citizens'][1:]]
  self.change('guard',account=self.b,building_id=p,citizen_id=ids[0]);self.change('patrol',account=self.b,citizen_id=ids[1]);uid=self.unit()
  self.raid(units=[uid]);self.advance(8200);report=self.report();self.assertEqual(len(report['defenders']),5);self.assertGreater(report['defense_strength'],60)
 def test_render_reports_and_support_controls(self):
  from game.views import render_page
  p=self.build('guard_post');html=render_page(self.state(),'token').decode()
  self.assertIn('Assign guard',html);self.assertIn('Support and defense',html)
  self.assertIn('Guard Post defense radius',html);self.assertIn('Trading Post',html)
 def test_public_support_construction_and_upgrade(self):
  before=self.state()['resources']['scrap'];self.change('build',building_type='salvage_depot',x=21,y=18)
  state=self.state();b=next(b for b in state['buildings'] if b['building_type']=='salvage_depot');self.assertEqual(before-state['resources']['scrap'],55)
  cid=state['citizens'][1]['citizen_id'];self.change('builder',building_id=b['building_id'],citizen_id=cid)
  state=self.advance(2500);self.assertEqual(next(b for b in state['buildings'] if b['building_type']=='salvage_depot')['status'],'active')
  self.change('upgrade',now=2500,building_id=b['building_id'],expected_level=1);self.change('builder',now=2500,building_id=b['building_id'],citizen_id=cid)
  state=self.advance(4900);self.assertEqual(next(b for b in state['buildings'] if b['building_type']=='salvage_depot')['level'],2)
 def test_final_window_blocks_launch_and_season_end_recalls_assets(self):
  uid=self.unit();self.sql('UPDATE seasons SET finalization_at=5000,ends_at=6000');self.raid(units=[uid]);self.advance(6000)
  self.assertEqual(self.state()['units'][0]['status'],'available');self.assertEqual(self.sql('SELECT status FROM attacks')[0][0],'cancelled')
  self.assertEqual(self.state()['settlement']['status'],'archived')
 def test_deployed_citizen_cannot_be_assigned_guard_or_patrol(self):
  cid=self.extra()[0];p=self.build('guard_post');self.raid(citizens=[cid])
  for action in ('guard','patrol'):
   with self.assertRaises(ValueError):self.change(action,now=4600,building_id=p,citizen_id=cid)
 def test_air_kill_prevents_resource_fight_and_loot(self):
  uid=self.unit(hp=5);self.unit('air_defense_drone',sid=self.sb);self.raid(units=[uid]);before=[c['current_hp'] for c in self.state(self.b)['citizens']]
  self.advance(8200);r=self.report();self.assertEqual(r['result'],'defender_win');self.assertEqual(r['attackers'],[]);self.assertEqual(r['defenders'],[]);self.assertEqual(r['loot']['taken'],{})
  self.assertEqual([c['current_hp'] for c in self.state(self.b)['citizens']],before)
 def test_offline_drone_resolution_matches_incremental_requests(self):
  self.weak();uid=self.unit();self.unit('air_defense_drone',sid=self.sb);self.raid(units=[uid]);clone=self.path.with_name('clone.db');shutil.copy2(self.path,clone)
  self.advance(8500);one=self.report();units=[(u['unit_type'],u['current_hp'],u['status']) for u in self.state()['units']];original=self.path;self.path=clone
  for now in range(4660,8501,60):self.advance(now)
  self.assertEqual(one,self.report());self.assertEqual(units,[(u['unit_type'],u['current_hp'],u['status']) for u in self.state()['units']]);self.path=original

 def test_unpowered_community_keeps_base_bonus_with_oxygen(self):
  self.sql("UPDATE buildings SET current_hp=0 WHERE building_type='wind_turbine'")
  self.build('oxygen_garden',x=29,y=18)
  p=self.build('community_center',x=29,y=21);self.staff(p,2)
  state=self.state();self.assertAlmostEqual(support.community(state),3)
  self.assertAlmostEqual(state['citizens'][0]['effective_morale'],63)
 def test_medical_needs_and_pause_stop_health_credit(self):
  p=self.build('clinic');self.staff(p,2);self.sql('UPDATE citizens SET current_hp=50')
  self.sql('UPDATE settlement_resources SET water=0');self.assertEqual(support.treatment(self.state()),{})
  self.sql('UPDATE settlement_resources SET water=100');self.sql("UPDATE seasons SET status='paused',paused_at=1000")
  self.advance(1600);self.assertTrue(all(c['current_hp']==50 for c in self.state()['citizens']))
 def test_engineering_actually_accelerates_construction_and_repairs(self):
  p=self.build('engineering_workshop');self.staff(p,2)
  self.change('build',building_type='garden',x=18,y=21)
  state=self.state();job=state['jobs'][0];builder=state['citizens'][-1]['citizen_id'];self.change('builder',building_id=job['target_building_id'],citizen_id=builder)
  state=self.state();self.assertAlmostEqual(job_speed(state,state['jobs'][0]),1.1)
  self.advance(1900)
  self.sql('UPDATE buildings SET current_hp=current_hp-50 WHERE building_id=?',(p,))
  self.change('repair',now=1900,building_id=p)
  self.change('repairer',now=1900,building_id=p,citizen_id=builder)
  state=self.state();repair=next(j for j in state['jobs'] if j['job_type']=='repair')
  self.assertGreater(job_speed(state,repair),1)

 def test_medical_with_no_usable_slots_does_not_block_basic_care(self):
  clinic=self.build('clinic');self.staff(clinic,1)
  center=self.build('medical_center',x=18,y=21,level=3);self.staff(center,1)
  self.sql('UPDATE buildings SET current_hp=current_hp*0.7 WHERE building_id=?',(center,))
  cid=self.state()['citizens'][-1]['citizen_id'];self.sql('UPDATE citizens SET current_hp=50 WHERE citizen_id=?',(cid,))
  care=support.treatment(self.state());self.assertEqual(care[cid]['building_id'],clinic);self.assertAlmostEqual(care[cid]['bonus'],12.5)

 def test_electricity_prioritizes_water_before_medical(self):
  from game.economy import utilities
  self.sql("UPDATE buildings SET current_hp=0 WHERE building_type='wind_turbine'")
  water=self.build('well_pump');self.staff(water,1)
  medical=self.build('medical_center',x=18,y=21);self.staff(medical,1)
  self.build('oxygen_garden',x=23,y=18)
  self.sql("UPDATE buildings SET current_hp=current_hp*0.4 WHERE building_type='town_hall'")
  status=utilities(self.state())['buildings'];self.assertEqual(status[water]['reason'],'');self.assertEqual(status[medical]['reason'],'Not enough electricity capacity')
 def test_oxygen_prioritizes_medical_before_water(self):
  from game.economy import utilities
  water=self.build('well_pump');self.staff(water,1)
  medical=self.build('clinic',x=18,y=21);self.staff(medical,1)
  self.sql("UPDATE buildings SET current_hp=current_hp*0.26 WHERE building_type='town_hall'")
  status=utilities(self.state())['buildings'];self.assertEqual(status[medical]['reason'],'');self.assertEqual(status[water]['reason'],'Not enough oxygen capacity')

class DefenseHTTPTests(unittest.TestCase):
 def setUp(self):
  from tests.fixtures import HTTPWorld
  self.h=HTTPWorld(self)
 def test_owned_defense_forms_csrf_origin_duplicate_fields_and_render(self):
  h=self.h;csrf=h.players[0][2]
  self.assertEqual(h.request('/buildings',{'action':'enable_support','token':'bad'})[0],403)
  self.assertEqual(h.request('/buildings',{'action':'enable_support','token':csrf},origin='https://example.com')[0],403)
  self.assertEqual(h.request('/buildings',{'action':'enable_support','token':csrf})[0],303)
  cid=h.state()['citizens'][1]['citizen_id'];foreign=h.state(1)['citizens'][1]['citizen_id']
  self.assertEqual(h.request('/buildings',{'action':'patrol','citizen_id':foreign,'token':csrf})[0],400)
  self.assertEqual(h.request('/buildings',{'action':'patrol','citizen_id':cid,'token':csrf})[0],303)
  self.assertEqual(h.request('/buildings',{'action':'release_defense','citizen_id':[cid,cid],'token':csrf})[0],400)
  status,body=h.request();self.assertEqual(status,200);self.assertIn(b'Support and defense',body);self.assertIn(b'Release defense assignment',body)
  self.assertEqual(h.request('/buildings',{'action':'release_defense','citizen_id':cid,'token':csrf})[0],303)
 def test_drone_fields_accept_multiple_but_reject_duplicate_ids_atomically(self):
  h=self.h;csrf=h.players[0][2];h.request('/buildings',{'action':'enable_support','token':csrf})
  with closing(connect_database(h.path)) as c,c:
   c.execute('DELETE FROM settlement_derelicts');c.execute('DELETE FROM season_derelicts');c.execute('UPDATE settlements SET protection_until=1000')
   c.execute("UPDATE buildings SET level=3,current_hp=2200 WHERE building_type='town_hall'")
   b=c.execute("INSERT INTO buildings(settlement_id,building_type,level,origin_x,origin_y,current_hp,status,created_at,completed_at) VALUES (1,'offensive_hangar',1,21,18,750,'active',1000,1000)").lastrowid
   ids=[c.execute("INSERT INTO military_units(settlement_id,unit_type,current_hp,home_building_id,status,created_at) VALUES (1,'offensive_drone',100,?,'available',1000)",(b,)).lastrowid for _ in range(2)]
  self.assertEqual(h.request('/conflict',{'action':'declare','target_id':2,'token':csrf})[0],303)
  h.server.clock=lambda:4600
  fields={'action':'launch','target_id':2,'drone_id':[ids[0],ids[0]],'token':csrf}
  self.assertEqual(h.request('/conflict',fields)[0],400)
  fields['drone_id']=ids;self.assertEqual(h.request('/conflict',fields)[0],303)
  self.assertTrue(all(u['status']=='deployed' for u in h.state()['units']))
  body=h.request(player=1)[1];self.assertIn(b'Incoming hostile attack',body);self.assertNotIn(b'Offensive Drone #',body)

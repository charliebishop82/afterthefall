"""Structural combat regression scenarios on disposable saves."""
from contextlib import closing
import json,sqlite3,unittest
from unittest.mock import patch
from tests.fixtures import SupportWorld
from game import combat,structural,ruins,manufacturing
from game.settlement import account_scope,read_state,load_config
from game.buildings import spec,job_speed,change_building
from database.create_database import connect_database

class StructuralTests(unittest.TestCase):
    def setUp(self):
        self.w=SupportWorld(self)
        self.w.change('enable_structural');self.w.config=load_config('prototype_v12')

    def connection(self,account=None):
        c=connect_database(self.w.path);c.row_factory=sqlite3.Row
        self.addCleanup(c.close)
        return c

    def hit(self,bid,damage,now=1000,account=None):
        c=self.connection()
        with c,account_scope(account or self.w.a):
            report=[];ruins.hit(c,read_state(c),bid,damage,now,None,report);return report

    def ammo(self,kind='missile',quantity=1,account=None,level=1):
        w=self.w;sid=w.sb if account==w.b else w.sa
        bid=w.build(w.config['units'][kind]['storage'],sid=sid,level=level)
        iid=w.sql('INSERT INTO military_inventory(settlement_id,building_id,unit_type,quantity,updated_at) VALUES (?,?,?,?,1000) RETURNING inventory_id',(sid,bid,kind,quantity))[0][0]
        return bid,iid

    def launch(self,quantity=1,objective='infrastructure',citizens=None,units=None):
        w=self.w
        with account_scope(w.a):
            if not w.sql("SELECT 1 FROM treaties WHERE treaty_type='war'"):combat.command(w.path,'declare',1000,target_id=w.sb)
            return combat.command(w.path,'launch',4600,target_id=w.sb,citizen_ids=citizens or [],drone_ids=units or [],missile_count=quantity,objective=objective)

    def test_version_activation_idempotent_and_new_player(self):
        w=self.w;before=w.state();w.change('enable_structural');self.assertEqual(before,w.state())
        w.player('charlie');self.assertEqual(w.state()['season']['config_version'],'prototype_v12')
        self.assertIsNone(w.state()['needs_clock'])

    def test_turret_costs_unlocks_and_power_requirements(self):
        config=self.w.config
        self.assertEqual(config['buildings']['automated_turret']['unlock'],2)
        self.assertEqual(config['buildings']['anti_air_turret']['unlock'],3)
        self.assertEqual([s['defense_strength'] for s in config['buildings']['automated_turret']['levels']],[18,28,42])
        self.assertEqual([s['hp'] for s in config['buildings']['anti_air_turret']['levels']],[380,540,740])
        self.assertTrue(config['buildings']['anti_air_turret']['electricity_required'])

    def test_missile_only_launch_spends_ammo_and_reserves_home_space(self):
        bid,iid=self.ammo(quantity=2);aid=self.launch()
        self.assertEqual(self.w.sql('SELECT quantity FROM military_inventory WHERE inventory_id=?',(iid,))[0][0],1)
        self.assertEqual(manufacturing.occupancy(self.w.state(),bid),2)
        self.assertEqual(self.w.sql('SELECT quantity,consumed_quantity FROM attack_munitions WHERE attack_id=?',(aid,))[0],(1,0))

    def test_invalid_ammunition_rolls_back_entire_launch(self):
        self.ammo();w=self.w
        with account_scope(w.a):combat.command(w.path,'declare',1000,target_id=w.sb)
        before=w.state()
        for count in (-1,2,1.5,True):
            with self.assertRaises(ValueError):self.launch(quantity=count)
        self.assertEqual(before,w.state())

    def test_missile_resolution_is_private_and_idempotent(self):
        self.ammo();aid=self.launch();w=self.w;w.advance(8200)
        reports=w.sql('SELECT report_data FROM battle_reports WHERE attack_id=?',(aid,));self.assertEqual(len(reports),2)
        report=json.loads(reports[0][0]);self.assertEqual(report['missiles']['launched'],1);self.assertTrue(report['missiles']['hits'])
        before=w.state();w.advance(8200);self.assertEqual(before,w.state())
        self.assertEqual(w.sql('SELECT consumed_quantity FROM attack_munitions WHERE attack_id=?',(aid,))[0][0],1)
        self.assertEqual(report['loot']['taken'],{})

    def test_interceptors_are_finite_and_record_workbook_odds(self):
        self.ammo(quantity=2);_,iid=self.ammo('interceptor',1,account=self.w.b,level=3)
        self.launch(quantity=2);self.w.advance(8200)
        report=self.w.report()['missiles'];self.assertEqual(len(report['interceptors']),1)
        self.assertEqual(report['interceptors'][0]['chance'],.75)
        self.assertEqual(self.w.sql('SELECT quantity FROM military_inventory WHERE inventory_id=?',(iid,))[0][0],0)

    def test_recalled_missiles_return_once_and_refund_allowance(self):
        _,iid=self.ammo();aid=self.launch();w=self.w
        w.sql('UPDATE settlements SET protection_until=20000 WHERE settlement_id=?',(w.sb,));w.advance(8200)
        self.assertEqual(w.sql('SELECT status,allowance_refunded FROM attacks WHERE attack_id=?',(aid,))[0],('cancelled',1))
        self.assertEqual(w.sql('SELECT quantity FROM military_inventory WHERE inventory_id=?',(iid,))[0][0],1)
        w.advance(8300);self.assertEqual(w.sql('SELECT quantity FROM military_inventory WHERE inventory_id=?',(iid,))[0][0],1)

    def test_rebuilding_recall_does_not_double_refund_stale_attack_rows(self):
        w=self.w;_,iid=self.ammo();aid=self.launch()
        c=self.connection()
        with c,account_scope(w.a):
            cached=c.execute('SELECT * FROM attacks WHERE attack_id=?',(aid,)).fetchone()
            combat.cancel(c,cached,4700,'Rebuilding protection')
            combat.resolve(c,cached,8200)
            combat.cancel(c,cached,8200,'Repeated stale delivery')
        self.assertEqual(w.sql('SELECT quantity FROM military_inventory WHERE inventory_id=?',(iid,))[0][0],1)
        self.assertEqual(w.state()['settlement']['attacks_remaining'],3)
        self.assertFalse(w.sql('SELECT 1 FROM battle_reports WHERE attack_id=?',(aid,)))

    def test_destroying_hangar_cancels_service_without_resurrecting_drone(self):
        w=self.w;uid=w.unit(hp=50);home=w.state()['units'][-1]['home_building_id']
        shop=w.build('engineering_workshop',x=24,y=18);w.staff(shop,2)
        w.change('service_drone',unit_id=uid,building_id=shop)
        self.hit(home,10000)
        state=w.advance(1060);u=next(u for u in state['units'] if u['unit_id']==uid)
        self.assertEqual((u['status'],u['current_hp']),('destroyed',0))
        self.assertEqual(next(j for j in state['jobs'] if j['job_type']=='drone_repair')['status'],'cancelled')

    def test_destroyed_building_releases_workers_and_blocks_tiles(self):
        w=self.w;bid=w.build('garden');cid=w.staff(bid)[0];self.hit(bid,1000)
        state=w.state();self.assertFalse(w.sql('SELECT 1 FROM citizen_assignments WHERE citizen_id=? AND ended_at IS NULL',(cid,)))
        self.assertEqual(w.sql('SELECT status FROM citizens WHERE citizen_id=?',(cid,))[0][0],'dead')
        self.assertEqual(next(b for b in state['buildings'] if b['building_id']==bid)['status'],'ruined')
        with self.assertRaises(ValueError):w.change('build',building_type='garden',x=21,y=18)

    def test_tents_leave_no_salvage_or_obstacle(self):
        w=self.w;bid=w.build('pup_tent');self.hit(bid,.1)
        self.assertEqual(w.state()['buildings'][-1]['status'],'cleared')
        w.change('build',building_type='garden',x=21,y=18)
        data=json.loads(w.sql("SELECT event_data FROM building_state_events WHERE building_id=? AND event_type='hostile_destruction'",(bid,))[0][0]);self.assertEqual(data['salvage'],{})

    def test_hall_survives_and_retains_oxygen_and_electricity(self):
        from game.economy import utilities
        w=self.w;bid=w.state()['buildings'][0]['building_id'];self.hit(bid,100000)
        state=w.state();self.assertEqual(state['buildings'][0]['current_hp'],spec(state,state['buildings'][0])['hp']*.25)
        u=utilities(state);self.assertTrue(u['zones']['oxygen']);self.assertTrue(u['zones']['electricity'])
        self.assertGreaterEqual(u['capacity']['oxygen'],load_config('prototype_v12')['buildings']['town_hall']['levels'][0]['oxygen_output'])

    def test_occupant_injury_uses_actual_building_hp_loss(self):
        w=self.w;bid=w.build('garden');cid=w.staff(bid)[0];hp=w.state()['buildings'][-1]['current_hp']
        self.hit(bid,hp*.2)
        citizen=next(c for c in w.state()['citizens'] if c['citizen_id']==cid)
        self.assertAlmostEqual(citizen['current_hp'],80)

    def test_salvage_progress_clear_and_rebuild_no_double_credit(self):
        w=self.w;bid=w.build('garden');self.hit(bid,1000)
        cid=w.state()['citizens'][1]['citizen_id'];w.change('salvage_ruin',building_id=bid,citizen_id=cid)
        state=w.advance(1600);job=next(j for j in state['jobs'] if j['job_type']=='building_salvage')
        self.assertGreater(job['work_completed'],0);self.assertLess(job['work_completed'],job['work_required'])
        self.assertGreater(state['resources']['scrap'],300)
        state=w.advance(4000);self.assertEqual(next(b for b in state['buildings'] if b['building_id']==bid)['status'],'cleared')
        before=state['resources']['scrap'];w.advance(4000);self.assertEqual(w.state()['resources']['scrap'],before)
        w.change('build',now=4000,building_type='garden',x=21,y=18)

    def test_unfinished_construction_salvage_scales_actual_progress(self):
        w=self.w;w.change('build',building_type='garden',x=24,y=18);b=w.state()['buildings'][-1]
        w.sql('UPDATE settlement_jobs SET work_completed=work_required*.5 WHERE target_building_id=?',(b['building_id'],))
        w.sql('UPDATE buildings SET current_hp=90 WHERE building_id=?',(b['building_id'],));self.hit(b['building_id'],1000)
        data=json.loads(w.sql("SELECT event_data FROM building_state_events WHERE building_id=? AND event_type='hostile_destruction'",(b['building_id'],))[0][0])
        self.assertAlmostEqual(data['salvage']['scrap'],spec(w.state(),b)['scrap']*.5*.35)
        self.assertEqual(data['work_required'],spec(w.state(),b)['minutes']*30)

    def test_secondary_explosions_consume_store_once(self):
        w=self.w;bid,iid=self.ammo(quantity=2);neighbor=w.build('garden',x=23,y=18)
        report=self.hit(bid,10000)
        self.assertEqual(w.sql('SELECT quantity FROM military_inventory WHERE inventory_id=?',(iid,))[0][0],0)
        self.assertTrue(any(h['building_id']==neighbor for h in report))
        before=w.state();self.hit(bid,10000);self.assertEqual(before,w.state())

    def test_turrets_scale_by_hp_radius_and_power(self):
        w=self.w;s=w.config['buildings']['automated_turret']['levels'][0]
        bid=w.sql("INSERT INTO buildings(settlement_id,building_type,origin_x,origin_y,level,current_hp,status,created_at,completed_at) VALUES (?,'automated_turret',21,18,1,?,'active',1000,1000) RETURNING building_id",(w.sa,s['hp']))[0][0]
        self.assertEqual(structural.turret_strength(w.state(),'automated_turret'),18)
        w.sql('UPDATE buildings SET current_hp=current_hp*.5 WHERE building_id=?',(bid,));self.assertEqual(structural.turret_strength(w.state(),'automated_turret'),9)
        w.sql('UPDATE buildings SET origin_x=38,origin_y=38 WHERE building_id=?',(bid,));self.assertEqual(structural.turret_strength(w.state(),'automated_turret'),0)

    def test_destroying_factory_cancels_paid_batch_and_workshop_service(self):
        from game.manufacturing import command
        w=self.w;factory=w.build('drone_factory');w.staff(factory,2);w.build('offensive_hangar',x=24,y=18)
        with account_scope(w.a):command(w.path,'queue',1000,building_id=factory,unit_type='offensive_drone')
        self.hit(factory,100000)
        self.assertTrue(all(j['status']=='cancelled' for j in w.state()['jobs'] if j['production_building_id']==factory))

    def test_rebuilding_shield_only_for_hostile_loss(self):
        w=self.w
        for b in list(w.state()['buildings'][1:]):self.hit(b['building_id'],100000)
        c=self.connection()
        with c,account_scope(w.a):structural.protect(c,read_state(c),1000)
        self.assertEqual(w.state()['settlement']['protection_type'],'rebuilding')
        until=w.state()['settlement']['protection_until']
        with c,account_scope(w.a):structural.protect(c,read_state(c),1001)
        self.assertEqual(w.state()['settlement']['protection_until'],until)

    def test_building_destruction_does_not_release_trade_reservations(self):
        w=self.w;bid=w.build('warehouse')
        from game.trading import transact
        with account_scope(w.a):transact(w.path,'propose',1000,recipient_id=w.sb,offered={'scrap':10},requested={'water':1})
        self.hit(bid,100000)
        self.assertEqual(w.state()['reserved']['scrap'],10)

    def test_cross_owner_salvage_is_rejected(self):
        w=self.w;bid=w.build('garden',sid=w.sb);self.hit(bid,10000,account=w.b)
        before=w.state()
        with self.assertRaises(ValueError):w.change('salvage_ruin',building_id=bid,citizen_id=w.state()['citizens'][1]['citizen_id'])
        self.assertEqual(before,w.state())


    def test_construction_progress_does_not_erase_hostile_damage(self):
        w=self.w;w.change('build',building_type='greenhouse',x=24,y=18);bid=w.state()['buildings'][-1]['building_id'];cid=w.state()['citizens'][1]['citizen_id']
        w.change('builder',building_id=bid,citizen_id=cid);w.advance(1300);before=w.state()['buildings'][-1]['current_hp']
        self.hit(bid,before*.5,now=1300);w.advance(1360)
        b=w.state()['buildings'][-1];j=next(j for j in w.state()['jobs'] if j['target_building_id']==bid)
        self.assertAlmostEqual(b['current_hp'],spec(w.state(),b)['hp']*j['work_completed']/j['work_required']-before*.5)

    def test_paid_repairs_extend_after_new_damage(self):
        w=self.w;bid=w.build('greenhouse');w.sql('UPDATE buildings SET current_hp=200 WHERE building_id=?',(bid,));w.change('repair',building_id=bid)
        cid=w.state()['citizens'][1]['citizen_id'];w.change('repairer',building_id=bid,citizen_id=cid)
        old=next(j for j in w.state()['jobs'] if j['job_type']=='repair');self.hit(bid,50)
        new=next(j for j in w.state()['jobs'] if j['job_type']=='repair')
        self.assertAlmostEqual(new['work_required']-old['work_required'],50/20*3600)
        w.advance(1060);self.assertLess(w.state()['buildings'][-1]['current_hp'],151)

    def test_deployed_drone_relocates_after_home_is_destroyed(self):
        from game import drones
        w=self.w;uid=w.unit();u=w.state()['units'][-1];spare=w.build('offensive_hangar',x=24,y=18)
        w.sql("UPDATE military_units SET status='deployed' WHERE unit_id=?",(uid,));self.hit(u['home_building_id'],10000)
        c=self.connection()
        with c,account_scope(w.a):
            current=read_state(c);unit=next(u for u in current['units'] if u['unit_id']==uid)
            hp=drones.return_home(c,current,unit,100,1000)
        self.assertEqual(hp,100);self.assertEqual(w.state()['units'][-1]['home_building_id'],spare)

    def test_air_turret_fights_drones_without_air_defense_units(self):
        w=self.w;uid=w.unit();s=w.config['buildings']['anti_air_turret']['levels'][2]
        w.sql("INSERT INTO buildings(settlement_id,building_type,origin_x,origin_y,level,current_hp,status,created_at,completed_at) VALUES (?,'anti_air_turret',21,18,3,?,'active',1000,1000)",(w.sb,s['hp']))
        aid=self.launch(quantity=0,units=[uid],objective='scrap');w.advance(8200)
        report=w.report();self.assertGreater(report['air_battle']['defense_strength'],0)
        self.assertEqual(report['air_battle']['defenders'],[])
        self.assertTrue(report['air_battle']['attackers'])

    def test_infrastructure_raid_deals_damage_without_loot(self):
        w=self.w;ids=w.extra(4);w.weak();aid=self.launch(quantity=0,citizens=ids)
        w.advance(8200);report=w.report();self.assertEqual(report['objective'],'infrastructure')
        self.assertEqual(report['loot']['taken'],{});self.assertTrue(report['building_damage'])

    def test_rebuilding_shield_rearms_after_three_functional_buildings(self):
        w=self.w
        for b in list(w.state()['buildings'][1:]):self.hit(b['building_id'],10000)
        c=self.connection()
        with c,account_scope(w.a):structural.protect(c,read_state(c),1000)
        for i in range(3):w.build('scrap_yard',x=21+i,y=23)
        with c,account_scope(w.a):structural.rearm(c,read_state(c),1100)
        self.assertTrue(w.sql("SELECT 1 FROM game_events WHERE settlement_id=? AND event_type='rebuilding_rearmed'",(w.sa,)))
        for b in list(w.state()['buildings'][1:]):
            if b['status']=='active':self.hit(b['building_id'],10000,now=1200)
        with c,account_scope(w.a):structural.protect(c,read_state(c),1200)
        self.assertEqual(w.state()['settlement']['protection_until'],1200+86400)

    def test_hall_damage_floor_applies_at_every_level_and_repeated_hits(self):
        w=self.w;bid=w.state()['buildings'][0]['building_id']
        for level in (1,2,3):
            maximum=w.config['buildings']['town_hall']['levels'][level-1]['hp']
            w.sql('UPDATE buildings SET level=?,current_hp=? WHERE building_id=?',(level,maximum,bid))
            report=self.hit(bid,maximum*10)
            self.assertEqual(report[0]['hp_after'],maximum*.25)
            before={c['citizen_id']:c['current_hp'] for c in w.state()['citizens']}
            self.hit(bid,maximum*10)
            self.assertEqual(w.state()['buildings'][0]['current_hp'],maximum*.25)
            self.assertEqual(before,{c['citizen_id']:c['current_hp'] for c in w.state()['citizens']})

    def test_legacy_hall_below_floor_is_not_healed_by_damage(self):
        w=self.w;bid=w.state()['buildings'][0]['building_id']
        w.sql('UPDATE buildings SET current_hp=1 WHERE building_id=?',(bid,))
        before={c['citizen_id']:c['current_hp'] for c in w.state()['citizens']}
        self.hit(bid,100000)
        self.assertEqual(w.state()['buildings'][0]['current_hp'],1)
        self.assertEqual(before,{c['citizen_id']:c['current_hp'] for c in w.state()['citizens']})


class StructuralHTTPTests(unittest.TestCase):
    def setUp(self):
        from tests.fixtures import HTTPWorld
        self.h=HTTPWorld(self)

    def test_activation_csrf_duplicate_fields_and_live_page(self):
        h=self.h;csrf=h.players[0][2]
        self.assertEqual(h.request('/buildings',{'action':'enable_structural','token':'wrong'})[0],403)
        self.assertEqual(h.request('/buildings',{'action':['enable_structural','enable_structural'],'token':csrf})[0],400)
        self.assertEqual(h.request('/buildings',{'action':'enable_structural','token':csrf})[0],303)
        self.assertEqual(h.request('/buildings',{'action':'enable_consequences','token':csrf})[0],303)
        self.assertEqual(h.state()['season']['config_version'],'prototype_v13')
        self.assertIn(b'Citizen wellbeing',h.request()[1])
        self.assertIn(b'Anti-Air Turret',h.request()[1])
        self.assertEqual(h.request('/api/resources')[0],200)

    def test_exposure_confirmation_and_expulsion_cannot_target_other_owner(self):
        h=self.h;csrf=h.players[0][2];h.request('/buildings',{'action':'enable_consequences','token':csrf})
        with closing(connect_database(h.path)) as c,c:
            c.execute('DELETE FROM settlement_derelicts');c.execute('DELETE FROM season_derelicts')
        self.assertEqual(h.request('/buildings',{'action':'build','building_type':'garden','x':35,'y':35,'token':csrf})[0],303)
        bid=h.state()['buildings'][-1]['building_id'];cid=h.state()['citizens'][1]['citizen_id']
        fields={'action':'builder','building_id':bid,'citizen_id':cid,'token':csrf}
        self.assertEqual(h.request('/buildings',fields)[0],400)
        fields['exposed']=['1','1'];self.assertEqual(h.request('/buildings',fields)[0],400)
        fields['exposed']='1';self.assertEqual(h.request('/buildings',fields)[0],303)
        self.assertEqual(h.request('/buildings',{'action':'expel','citizen_id':cid,'token':h.players[1][2]},player=1)[0],400)

    def test_missile_field_validation_keeps_attack_inventory_atomic(self):
        h=self.h;csrf=h.players[0][2];h.request('/buildings',{'action':'enable_structural','token':csrf})
        fields={'action':'launch','target_id':2,'missile_count':['1','1'],'token':csrf}
        self.assertEqual(h.request('/conflict',fields)[0],400)
        fields['missile_count']='1.5';self.assertEqual(h.request('/conflict',fields)[0],400)
        self.assertEqual(h.state()['settlement']['attacks_remaining'],3)


"""Paid maintenance and safe building removal using disposable controlled saves."""
import json
import shutil
import unittest
from tests.fixtures import SupportWorld,baseline_world
from game import maintenance,building_management,drones
from game.buildings import spec,job_speed
from game.settlement import account_scope,load_config,read_settlement
from game.views import render_page


def maintenance_baseline(owner):
    world=SupportWorld(owner)
    world.change('enable_maintenance')
    world.config=load_config('prototype_v11')
    return world


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.w=baseline_world(self,'maintenance',maintenance_baseline)

    def shop(self):
        bid=self.w.build('engineering_workshop',x=21,y=18)
        self.w.staff(bid,2)
        return bid

    def damage(self,bid,hp):self.w.sql('UPDATE buildings SET current_hp=? WHERE building_id=?',(hp,bid))

    def job(self,kind):return next(j for j in reversed(self.w.state()['jobs']) if j['job_type']==kind)

    def test_activation_repeat_and_late_join_preserve_catalog(self):
        w=self.w;before=w.state();w.change('enable_maintenance');self.assertEqual(before,w.state())
        w.player('charlie');self.assertEqual(w.state()['season']['config_version'],'prototype_v11')
        self.assertIsNone(w.state()['needs_clock'])

    def test_cancel_zero_progress_refunds_ninety_percent_and_reuses_tiles(self):
        w=self.w;before=w.state()['resources'];w.change('build',building_type='garden',x=24,y=18)
        b=w.state()['buildings'][-1];j=self.job('construction');w.change('cancel_build',building_id=b['building_id'])
        state=w.state();self.assertEqual(state['buildings'][-1]['status'],'demolished')
        spent=json.loads(j['inputs_spent'])
        for r in building_management.MATERIALS:self.assertAlmostEqual(state['resources'][r],before[r]-spent[r]*.1)
        after=state;w.change('cancel_build',building_id=b['building_id']);self.assertEqual(after,w.state())
        w.change('build',building_type='garden',x=24,y=18)
        self.assertEqual(w.state()['buildings'][-1]['status'],'construction')

    def test_cancel_progress_curve_releases_builders_and_retains_history(self):
        w=self.w;w.change('build',building_type='garden',x=24,y=18);bid=w.state()['buildings'][-1]['building_id']
        cid=w.state()['citizens'][1]['citizen_id'];w.change('builder',building_id=bid,citizen_id=cid)
        w.advance(1300);j=self.job('construction');before=w.state()['resources'];fraction=.9-.65*j['work_completed']/j['work_required']
        w.change('cancel_build',building_id=bid,now=1300)
        self.assertEqual(w.state()['citizens'][1]['assignment'],'unassigned')
        self.assertEqual(self.job('construction')['status'],'cancelled')
        self.assertAlmostEqual(w.state()['resources']['scrap']-before['scrap'],json.loads(j['inputs_spent'])['scrap']*fraction)
        self.assertTrue(w.sql("SELECT 1 FROM building_state_events WHERE building_id=? AND event_type='cancel_build'",(bid,)))

    def test_cancel_upgrade_preserves_level_hp_and_workers(self):
        w=self.w;bid=w.build('greenhouse');w.staff(bid)
        w.change('upgrade',building_id=bid,expected_level=1);before=w.state()['buildings'][-1]
        w.change('cancel_build',building_id=bid)
        after=w.state()['buildings'][-1];self.assertEqual(after['level'],1);self.assertEqual(after['current_hp'],before['current_hp']);self.assertEqual(after['status'],'active')
        self.assertEqual(w.state()['citizens'][1]['assignment'],'production')

    def test_completed_build_cannot_be_cancelled_and_hall_cannot_be_demolished(self):
        w=self.w;bid=w.build('garden')
        for action,target in [('cancel_build',bid),('demolish',w.state()['buildings'][0]['building_id'])]:
            before=w.state()
            with self.assertRaises(ValueError):w.change(action,building_id=target)
            self.assertEqual(before,w.state())

    def test_demolition_all_materials_cumulative_levels_and_repeat(self):
        w=self.w;bid=w.build('greenhouse',level=2);w.staff(bid)
        before=w.state();b=before['buildings'][-1];expected=building_management.recovery(before,b)
        w.change('demolish',building_id=bid);after=w.state()
        for r in building_management.MATERIALS:self.assertAlmostEqual(after['resources'][r]-before['resources'][r],expected[r])
        self.assertEqual(after['citizens'][1]['assignment'],'unassigned')
        self.assertEqual(after['buildings'][-1]['status'],'demolished')
        w.change('demolish',building_id=bid);self.assertEqual(after,w.state())
        self.assertNotIn(f'id="building-{bid}"',render_page(after,'token').decode())

    def test_demolition_uses_actual_investment_history(self):
        w=self.w;w.change('build',building_type='garden',x=24,y=18);bid=w.state()['buildings'][-1]['building_id'];j=self.job('construction')
        w.sql("UPDATE buildings SET status='active',current_hp=180 WHERE building_id=?",(bid,))
        w.sql("UPDATE settlement_jobs SET status='completed',work_completed=work_required WHERE job_id=?",(j['job_id'],))
        b=w.state()['buildings'][-1]
        self.assertAlmostEqual(building_management.recovery(w.state(),b)['scrap'],json.loads(j['inputs_spent'])['scrap']*.4)

    def test_demolition_rejects_stored_deployed_assets_and_pending_projects(self):
        w=self.w;uid=w.unit();bid=w.state()['units'][-1]['home_building_id']
        for status in ('available','deployed','repairing'):
            w.sql('UPDATE military_units SET status=? WHERE unit_id=?',(status,uid))
            with self.assertRaises(ValueError):w.change('demolish',building_id=bid)
        w.change('build',building_type='garden',x=24,y=18)
        with self.assertRaises(ValueError):w.change('demolish',building_id=w.state()['buildings'][-1]['building_id'])

    def test_demolition_rejects_storage_loss_and_preserves_reserved_resources(self):
        w=self.w;bid=w.build('warehouse');w.sql('UPDATE settlement_resources SET scrap=500,metal=300,electronics=100 WHERE settlement_id=?',(w.sa,))
        from game.trading import transact
        with account_scope(w.a):transact(w.path,'propose',1000,recipient_id=w.sb,offered={'scrap':500},requested={'metal':1})
        before=w.state()
        with self.assertRaises(ValueError):w.change('demolish',building_id=bid)
        self.assertEqual(before,w.state())

    def test_demolition_preserves_inaccessible_cold_storage_food(self):
        w=self.w;bid=w.build('cold_storage');w.sql('UPDATE settlement_resources SET food=400 WHERE settlement_id=?',(w.sa,))
        w.sql("UPDATE buildings SET current_hp=0 WHERE building_type='wind_turbine'")
        w.sql("UPDATE buildings SET current_hp=1900*0.26 WHERE building_type='town_hall'")
        w.advance(1001);before=w.state()
        from game.economy import food_lock
        self.assertGreater(food_lock(before)['protected_food'],0)
        with self.assertRaises(ValueError):w.change('demolish',building_id=bid,now=1001)
        self.assertEqual(before,w.state())

    def test_recovery_caps_at_free_shared_storage(self):
        w=self.w;bid=w.build('garden');cap=__import__('game.economy',fromlist=['storage']).storage(w.state())['material']
        w.sql('UPDATE settlement_resources SET scrap=?,metal=0,electronics=0 WHERE settlement_id=?',(cap-1,w.sa))
        w.change('demolish',building_id=bid);self.assertAlmostEqual(w.state()['resources']['scrap'],cap)
        event=json.loads(w.sql("SELECT event_data FROM building_state_events WHERE building_id=? ORDER BY state_event_id DESC",(bid,))[0][0])
        self.assertAlmostEqual(event['delivered']['scrap'],1)

    def test_ownership_of_building_drone_and_workshop(self):
        w=self.w;bid=w.build('garden');shop=self.shop();uid=w.unit(hp=70)
        for action,args in [('demolish',{'building_id':bid}),('service_drone',{'unit_id':uid,'building_id':shop})]:
            with self.assertRaises(ValueError):w.change(action,account=w.b,**args)

    def test_service_cost_completion_repeat_and_storage_reserved(self):
        w=self.w;shop=self.shop();uid=w.unit(hp=70);before=w.state();u=before['units'][-1];price=maintenance.repair_cost(before,u)
        w.change('service_drone',unit_id=uid,building_id=shop);state=w.state()
        for r in price:self.assertAlmostEqual(before['resources'][r]-state['resources'][r],price[r])
        self.assertEqual(state['units'][-1]['status'],'repairing');self.assertNotIn(uid,[u['unit_id'] for u in drones.ready(state,'offensive_drone')])
        w.change('service_drone',unit_id=uid,building_id=shop);self.assertEqual(state,w.state())
        state=w.advance(11800);self.assertEqual(state['units'][-1]['status'],'available');self.assertAlmostEqual(state['units'][-1]['current_hp'],100)
        self.assertEqual(self.job('drone_repair')['status'],'completed')

    def test_workshop_loss_pauses_and_restoration_resumes_service(self):
        w=self.w;shop=self.shop();uid=w.unit(hp=50);w.change('service_drone',unit_id=uid,building_id=shop)
        w.advance(1060);hp=w.state()['units'][-1]['current_hp'];self.assertAlmostEqual(hp,50+1/6)
        self.damage(shop,1);w.advance(1120);self.assertAlmostEqual(w.state()['units'][-1]['current_hp'],hp)
        self.damage(shop,w.config['buildings']['engineering_workshop']['levels'][0]['hp'])
        w.advance(1180);self.assertAlmostEqual(w.state()['units'][-1]['current_hp'],hp+1/6)

    def test_service_rejects_full_destroyed_deployed_and_busy_workshop(self):
        w=self.w;shop=self.shop();uid=w.unit()
        with self.assertRaises(ValueError):w.change('service_drone',unit_id=uid,building_id=shop)
        for status,hp in [('destroyed',0),('deployed',50)]:
            w.sql('UPDATE military_units SET status=?,current_hp=? WHERE unit_id=?',(status,hp,uid))
            with self.assertRaises(ValueError):w.change('service_drone',unit_id=uid,building_id=shop)
        w.sql("UPDATE military_units SET status='available',current_hp=50 WHERE unit_id=?",(uid,))
        w.change('service_drone',unit_id=uid,building_id=shop);other=w.unit(hp=70)
        with self.assertRaises(ValueError):w.change('service_drone',unit_id=other,building_id=shop)

    def test_repair_drone_manual_health_scaled_no_citizen_xp(self):
        w=self.w;shop=self.shop();uid=w.unit('repair_drone',home=shop,hp=40);bid=w.build('garden',x=24,y=18);self.damage(bid,100)
        w.change('repair_drone_target',unit_id=uid,building_id=bid)
        state=w.state();job=self.job('repair');self.assertAlmostEqual(job_speed(state,job),.25*(1+0))
        xp=[c['xp'] for c in state['citizens'] if c['assignment']=='unassigned'];state=w.advance(4600)
        self.assertAlmostEqual(next(b['current_hp'] for b in state['buildings'] if b['building_id']==bid),105)
        self.assertEqual(xp,[c['xp'] for c in state['citizens'] if c['assignment']=='unassigned'])

    def test_repair_drone_stop_preserves_paid_project_and_materials(self):
        w=self.w;shop=self.shop();uid=w.unit('repair_drone',home=shop);bid=w.build('garden',x=24,y=18);self.damage(bid,100)
        w.change('repair_drone_target',unit_id=uid,building_id=bid);before=w.state()['resources']
        w.change('repair_drone_off',unit_id=uid);self.assertEqual(before,w.state()['resources'])
        state=w.advance(1060);self.assertEqual(next(b['current_hp'] for b in state['buildings'] if b['building_id']==bid),100)
        self.assertEqual(self.job('repair')['status'],'paused')

    def test_auto_chooses_most_damaged_and_does_not_double_pay(self):
        w=self.w;shop=self.shop();uid=w.unit('repair_drone',home=shop);one=w.build('garden',x=24,y=18);two=w.build('garden',x=25,y=18)
        self.damage(one,100);self.damage(two,50);w.change('repair_drone_auto',unit_id=uid);w.advance(1001)
        state=w.state();self.assertEqual(state['repair_drone_orders'][str(uid)]['target'],two)
        self.assertEqual(len([j for j in state['jobs'] if j['job_type']=='repair']),1)
        price=state['resources']['metal'];w.change('repair_drone_auto',unit_id=uid,now=1001);w.advance(1060)
        self.assertEqual(w.state()['resources']['metal'],price)
        self.assertEqual(len([j for j in w.state()['jobs'] if j['job_type']=='repair']),1)

    def test_auto_insufficient_funds_does_not_create_debt(self):
        w=self.w;shop=self.shop();uid=w.unit('repair_drone',home=shop);bid=w.build('garden',x=24,y=18);self.damage(bid,100)
        w.sql('UPDATE settlement_resources SET scrap=0,metal=0,electronics=0 WHERE settlement_id=?',(w.sa,));w.change('repair_drone_auto',unit_id=uid);w.advance(1060)
        self.assertFalse([j for j in w.state()['jobs'] if j['job_type']=='repair'])
        self.assertEqual(w.state()['resources']['scrap'],0)

    def test_unaffordable_auto_hall_repair_preserves_pending_regeneration(self):
        w=self.w;shop=self.shop();uid=w.unit('repair_drone',home=shop)
        self.damage(w.state()['buildings'][0]['building_id'],1800)
        w.sql('UPDATE settlement_resources SET scrap=0,metal=0,electronics=0 WHERE settlement_id=?',(w.sa,))
        w.change('repair_drone_auto',unit_id=uid)
        from contextlib import closing
        from database.create_database import connect_database
        from game.settlement import read_state
        import sqlite3
        with account_scope(w.a),closing(connect_database(w.path)) as c,c:
            c.row_factory=sqlite3.Row
            from game.simulation import _event
            state=read_state(c);_event(c,state,'prototype_regen_clock',1000,{'pending':1})
            before=list(c.iterdump());self.assertFalse(maintenance.prepare(c,read_state(c),1000))
            self.assertEqual(before,list(c.iterdump()))

    def test_manual_repair_joins_existing_project_without_charging_again(self):
        w=self.w;shop=self.shop();uid=w.unit('repair_drone',home=shop);bid=w.build('garden',x=24,y=18);self.damage(bid,100)
        w.change('repair',building_id=bid);before=w.state()['resources'];w.change('repair_drone_target',unit_id=uid,building_id=bid)
        self.assertEqual(before,w.state()['resources']);self.assertEqual(len([j for j in w.state()['jobs'] if j['job_type']=='repair']),1)

    def test_manual_finishes_once_and_auto_moves_to_next_target(self):
        w=self.w;shop=self.shop();uid=w.unit('repair_drone',home=shop);one=w.build('garden',x=24,y=18);two=w.build('garden',x=25,y=18)
        maximum=w.config['buildings']['garden']['levels'][0]['hp'];self.damage(one,maximum-1);self.damage(two,maximum-.5)
        w.change('repair_drone_auto',unit_id=uid);state=w.advance(1600)
        self.assertEqual(len([j for j in state['jobs'] if j['job_type']=='repair' and j['status']=='completed']),2)
        self.assertAlmostEqual(next(b['current_hp'] for b in state['buildings'] if b['building_id']==one),maximum)
        self.damage(one,maximum-1);w.change('repair_drone_target',unit_id=uid,building_id=one,now=1600);w.advance(1961)
        self.assertEqual(w.state()['repair_drone_orders'][str(uid)]['mode'],'off')
        before=len(w.state()['jobs']);self.damage(one,maximum-1);w.advance(2021);self.assertEqual(len(w.state()['jobs']),before)

    def test_drone_service_cannot_spend_trade_reservations(self):
        w=self.w;shop=self.shop();uid=w.unit(hp=50)
        from game.trading import transact
        with account_scope(w.a):transact(w.path,'propose',1000,recipient_id=w.sb,offered={'metal':100,'electronics':50},requested={'scrap':1})
        before=w.state()
        with self.assertRaises(ValueError):w.change('service_drone',unit_id=uid,building_id=shop)
        self.assertEqual(before,w.state())

    def test_service_offline_equals_split_reads_after_restart(self):
        w=self.w;shop=self.shop();uid=w.unit(hp=50);w.change('service_drone',unit_id=uid,building_id=shop)
        clone=w.path.with_name('service-clone.db');shutil.copy2(w.path,clone);one=w.advance(1600)
        from game.simulation import advance_settlement
        with account_scope(w.a):
            for t in (1011,1060,1222,1600):two=advance_settlement(clone,t)
            two=read_settlement(clone)
        self.assertAlmostEqual(one['units'][-1]['current_hp'],two['units'][-1]['current_hp'])
        self.assertAlmostEqual(one['jobs'][-1]['work_completed'],two['jobs'][-1]['work_completed'])

    def test_automatic_repair_and_service_offline_equal_arbitrary_reads(self):
        w=self.w;shop=self.shop();uid=w.unit('repair_drone',home=shop);bid=w.build('garden',x=24,y=18);self.damage(bid,100);w.change('repair_drone_auto',unit_id=uid)
        clone=w.path.with_name('clone.db');shutil.copy2(w.path,clone)
        one=w.advance(1600)
        with account_scope(w.a):
            from game.simulation import advance_settlement
            for t in (1007,1031,1060,1111,1300,1600):two=advance_settlement(clone,t)
        for b,c in zip(one['buildings'],two['buildings']):self.assertAlmostEqual(b['current_hp'],c['current_hp'])
        for r in building_management.MATERIALS:self.assertAlmostEqual(one['resources'][r],two['resources'][r])

    def test_paused_time_and_final_window(self):
        w=self.w;shop=self.shop();uid=w.unit(hp=50);w.sql("UPDATE seasons SET status='paused',paused_at=1000")
        w.change('service_drone',unit_id=uid,building_id=shop);w.advance(4600);self.assertEqual(w.state()['units'][-1]['current_hp'],50)
        w.sql("UPDATE seasons SET status='active',paused_at=NULL,finalization_at=1000")
        other=w.unit(hp=50)
        with self.assertRaises(ValueError):w.change('service_drone',unit_id=other,building_id=shop)

    def test_season_end_releases_unfinished_service(self):
        w=self.w;shop=self.shop();uid=w.unit(hp=50);w.change('service_drone',unit_id=uid,building_id=shop)
        w.sql('UPDATE seasons SET ends_at=1060,finalization_at=1000');state=w.advance(1060)
        self.assertEqual(state['units'][-1]['status'],'available');self.assertEqual(self.job('drone_repair')['status'],'cancelled')
        self.assertEqual(state['season']['status'],'finished')

    def test_render_exposes_actions_and_permanent_demolition_confirmation(self):
        w=self.w;shop=self.shop();w.unit('repair_drone',home=shop);w.unit(hp=70);bid=w.build('garden',x=24,y=18)
        html=render_page(w.state(),'csrf-token').decode()
        for text in ('Drone maintenance','Confirm permanent demolition','service_drone','repair_drone_auto','Demolish building #'):
            self.assertIn(text,html)


class MaintenanceHTTPTests(unittest.TestCase):
    def setUp(self):
        from tests.fixtures import HTTPWorld
        self.h=HTTPWorld(self)

    def test_cancel_demolish_forms_auth_ownership_and_duplicates(self):
        h=self.h;csrf=h.players[0][2]
        self.assertEqual(h.request('/buildings',{'action':'enable_maintenance','token':'wrong'})[0],403)
        self.assertEqual(h.request('/buildings',{'action':'enable_maintenance','token':csrf},origin='https://example.com')[0],403)
        self.assertEqual(h.request('/buildings',{'action':'enable_maintenance','token':csrf})[0],303)
        from contextlib import closing
        from database.create_database import connect_database
        with closing(connect_database(h.path)) as c,c:
            c.execute('DELETE FROM settlement_derelicts');c.execute('DELETE FROM season_derelicts')
        self.assertEqual(h.request('/buildings',{'action':'build','building_type':'garden','x':21,'y':18,'token':csrf})[0],303)
        bid=h.state()['buildings'][-1]['building_id']
        self.assertEqual(h.request('/buildings',{'action':'cancel_build','building_id':bid,'token':h.players[1][2]},player=1)[0],400)
        self.assertEqual(h.request('/buildings',{'action':'cancel_build','building_id':[bid,bid],'token':csrf})[0],400)
        self.assertEqual(h.request('/buildings',{'action':'cancel_build','building_id':bid,'token':csrf})[0],303)
        self.assertEqual(h.state()['buildings'][-1]['status'],'demolished')
        self.assertEqual(h.request('/buildings',{'action':'demolish','building_id':h.state()['buildings'][0]['building_id'],'token':csrf})[0],400)

    def test_drone_service_http_reserves_unit_and_rejects_duplicate_unit_fields(self):
        h=self.h;csrf=h.players[0][2];h.request('/buildings',{'action':'enable_maintenance','token':csrf})
        from contextlib import closing
        from database.create_database import connect_database
        with closing(connect_database(h.path)) as c,c:
            c.execute('DELETE FROM settlement_derelicts');c.execute('DELETE FROM season_derelicts')
            c.execute("UPDATE buildings SET level=3,current_hp=1900 WHERE building_type='town_hall'")
            shop=c.execute("INSERT INTO buildings(settlement_id,building_type,level,origin_x,origin_y,current_hp,status,created_at,completed_at) VALUES (1,'engineering_workshop',1,21,18,450,'active',1000,1000)").lastrowid
            uid=c.execute("INSERT INTO military_units(settlement_id,unit_type,current_hp,home_building_id,status,created_at) VALUES (1,'repair_drone',40,?,'available',1000)",(shop,)).lastrowid
            for row in c.execute('SELECT citizen_id FROM citizens WHERE settlement_id=1 AND citizen_id IN (2,3)').fetchall():
                c.execute("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,building_id,assigned_at) VALUES (?,1,'production',?,1000)",(row[0],shop))
        fields={'action':'service_drone','unit_id':[uid,uid],'building_id':shop,'token':csrf}
        self.assertEqual(h.request('/buildings',fields)[0],400)
        fields['unit_id']=uid;self.assertEqual(h.request('/buildings',fields)[0],303)
        self.assertEqual(h.state()['units'][-1]['status'],'repairing')
        self.assertEqual(h.request('/buildings',{'action':'repair_drone_auto','unit_id':uid,'token':csrf})[0],400)
        self.assertIn(b'Service progress',h.request()[1])

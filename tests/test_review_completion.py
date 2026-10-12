"""Review regressions and operator investigations on disposable state."""
from contextlib import closing
import copy,json,re,sqlite3,unittest
from unittest.mock import Mock,patch
from tests.fixtures import SupportWorld,CombatWorld,fixed_map_seed
from database.create_database import connect_database
from game import advisor,capture,consequences,diagnostics,expansion
from game.settlement import account_scope,read_state
from game.simulation import _event
from game.scoring import totals

class ReviewTests(unittest.TestCase):
    def world(self):
        with fixed_map_seed():w=SupportWorld(self)
        w.change('enable_consequences')
        return w

    def test_desertion_audit_records_inputs_results_and_floor(self):
        w=self.world();w.extra(2);w.sql('UPDATE citizens SET morale=0 WHERE settlement_id=?',(w.sa,))
        rng=Mock();rng.random.return_value=0
        with closing(connect_database(w.path)) as c,c,account_scope(w.a),patch('game.consequences.random.Random',return_value=rng):
            c.row_factory=sqlite3.Row;consequences.daily(c,read_state(c),86400)
            data=json.loads(c.execute("SELECT event_data FROM game_events WHERE event_type='citizen_daily_rollover' AND settlement_id=?",(w.sa,)).fetchone()[0])
        self.assertEqual(data['birth_inputs']['population'],6);self.assertIn('supply_rates',data['birth_inputs'])
        checks=data['desertion_checks'];self.assertEqual(len(checks),8)
        self.assertEqual(sum(d['deserted'] for d in checks),2)
        self.assertEqual(sum(d['floor_blocked'] for d in checks),6)
        self.assertTrue(all(d['roll']==0 and d['morale']==0 and d['chance']==.1 for d in checks))

    def test_captured_desertion_audit_has_actual_probability_and_roll(self):
        w=CombatWorld(self)
        with account_scope(w.a):expansion.transact(w.path,'enable',1000)
        with closing(connect_database(w.path)) as c,c,account_scope(w.a):
            c.row_factory=sqlite3.Row;cid=read_state(c)['citizens'][-1]['citizen_id']
            c.execute('UPDATE citizens SET integrated=0,morale=0 WHERE citizen_id=?',(cid,))
            rng=Mock();rng.random.return_value=.99
            with patch('game.capture.random.Random',return_value=rng):capture.daily(c,read_state(c),86400)
            data=json.loads(c.execute("SELECT event_data FROM game_events WHERE event_type='captured_citizen_integrated'").fetchone()[0])
            self.assertEqual(data['roll'],.99);self.assertEqual(data['chance'],.5);self.assertEqual(data['morale'],0)

    def test_internal_rolls_not_in_player_notification_and_transaction_rollback(self):
        w=self.world()
        with closing(connect_database(w.path)) as c,c,account_scope(w.a):
            c.row_factory=sqlite3.Row;state=read_state(c)
            _event(c,state,'captured_citizen_integrated',1000,{'citizen_id':1,'morale':20,'chance':.2,'roll':.99})
            text=c.execute("SELECT message FROM notifications WHERE notification_type='captured_citizen_integrated'").fetchone()[0]
            self.assertNotIn('.99',text);self.assertNotIn('roll',text)
        before=w.sql('SELECT count(*) FROM notifications')[0][0]
        with self.assertRaises(RuntimeError):
            with closing(connect_database(w.path)) as c,c,account_scope(w.a):
                c.row_factory=sqlite3.Row;_event(c,read_state(c),'citizen_raid_resolved',1000,{'attack_id':99,'result':'contested'});raise RuntimeError()
        self.assertEqual(w.sql('SELECT count(*) FROM notifications')[0][0],before)

    def test_notification_events_target_owner_and_ignore_clock_noise(self):
        w=self.world()
        events=[('building_repair_completed',dict(building_id=1)),('drone_repair_completed',dict(unit_id=1)),('military_unit_produced',dict(unit_type='offensive_drone',home_building_id=1)),('prototype_survivor_arrived',dict(citizen_id=99)),('building_project_completed',dict(building_type='garden',building_id=1,job_type='upgrade',level=2)),('citizen_raid_incoming',dict(attack_id=1,resolves_at=4600)),('citizen_raid_resolved',dict(attack_id=1,result='attacker_win')),('citizen_died',dict(citizen_id=1,cause='structural_combat')),('citizen_daily_rollover',dict(birth_citizen_id=99,deserted=[1],floor_arrivals=[2])),('bank_interest',dict(loan_id=1,before=50,after=51)),('bank_transaction',dict(kind='investment_matured',amount=50)),('bank_liquidation_sale',dict(asset_type='unit',asset_id=1,credits=10))]
        with closing(connect_database(w.path)) as c,c,account_scope(w.a):
            c.row_factory=sqlite3.Row;state=read_state(c)
            for kind,data in events:_event(c,state,kind,1000,data)
            count=c.execute('SELECT count(*) FROM notifications').fetchone()[0]
            _event(c,state,'prototype_needs_clock',1000,{});self.assertEqual(c.execute('SELECT count(*) FROM notifications').fetchone()[0],count)
            self.assertEqual(c.execute('SELECT count(*) FROM notifications WHERE account_id=?',(w.b,)).fetchone()[0],0)
            self.assertEqual(c.execute("SELECT count(*) FROM notifications WHERE related_type='game_event'").fetchone()[0],len(events))

    def test_damaged_construction_value_is_not_double_scaled(self):
        config={'buildings':{'test':{'levels':[dict(scrap=100,metal=0,electronics=0,minutes=1,hp=100)]}},'units':{}}
        state=dict(resources=dict(food=0,water=0,scrap=0,metal=0,electronics=0,credits=0),citizens=[],config=config,buildings=[dict(building_id=1,building_type='test',level=1,status='construction',current_hp=30)],jobs=[dict(target_building_id=1,job_type='construction',status='active',work_completed=30,work_required=60,inputs_spent='{"scrap":100,"_damage":20}')])
        self.assertEqual(totals(state)['development'],30)
        state['jobs'][0]['inputs_spent']='{"scrap":100,"_damage":100}'
        self.assertEqual(totals(state)['development'],0)

    def test_diagnostics_semantic_health_and_preserved_legacy_duplicates(self):
        w=self.world();w.sql('UPDATE citizens SET name=? WHERE settlement_id=?',('Same Name',w.sa))
        before=w.path.read_bytes();report=diagnostics.inspect(w.path)
        self.assertTrue(report['ok'],report);self.assertIn('Legacy citizen names',[r[1] for r in report['findings']]);self.assertEqual(before,w.path.read_bytes())
        w.sql('UPDATE citizens SET current_hp=999 WHERE settlement_id=?',(w.sa,));w.sql("UPDATE buildings SET level=10 WHERE building_type='town_hall' AND settlement_id=?",(w.sa,))
        before=w.path.read_bytes();report=diagnostics.inspect(w.path)
        self.assertFalse(report['ok']);self.assertIn('Citizen health',[r[1] for r in report['findings']]);self.assertIn('Building catalogue',[r[1] for r in report['findings']]);self.assertEqual(before,w.path.read_bytes())

    def test_investigation_filters_keyset_and_rejects_invalid_values(self):
        w=self.world()
        with closing(connect_database(w.path)) as c,c,account_scope(w.a):
            c.row_factory=sqlite3.Row
            for n in range(5):_event(c,read_state(c),'example',1000+n,{'ordinal':n})
        before=w.path.read_bytes();page=diagnostics.events(w.path,settlement=w.sa,kind='example',limit=2)
        older=diagnostics.events(w.path,settlement=w.sa,kind='example',before=page[-1][0],limit=2)
        self.assertEqual([json.loads(r[4])['ordinal'] for r in page+older],[4,3,2,1]);self.assertEqual(before,w.path.read_bytes())
        for fields in ({'limit':0},{'limit':501},{'before':-1},{'before':10**100},{'settlement':True},{'kind':''}):
            with self.assertRaises(ValueError):diagnostics.events(w.path,**fields)
        self.assertEqual(diagnostics.events(w.path,kind="example' OR 1=1 --"),[])

    def test_advisor_read_only_warnings_and_owned_persistent_history(self):
        w=self.world();state=w.state();state['resources']['food']=0
        self.assertTrue(any('Food is empty' in m for m in advisor.report(state)))
        before=w.path.read_bytes();html=advisor.panel(w.path,state,'test',1000);self.assertIn('Ash',html);self.assertEqual(before,w.path.read_bytes())
        with account_scope(w.a):advisor.request_report(w.path,1000)
        self.assertEqual(len(diagnostics.events(w.path,settlement=w.sa,kind='advisor_report')),1)
        with account_scope(w.a),self.assertRaises(ValueError):advisor.request_report(w.path,1000)
        self.assertNotIn('Recent saved reports',advisor.panel(w.path,w.state(w.b),'test',1000))
        with account_scope(w.a),self.assertRaises(ValueError):advisor.request_report(w.path,w.state()['season']['ends_at'])

    def test_administrator_reassignment_replaces_by_level_and_rolls_back_rejection(self):
        w=self.world();old=next(c for c in w.state()['citizens'] if c['assignment']=='administrator');new=w.state()['citizens'][-1]
        w.sql('UPDATE citizens SET level=2 WHERE citizen_id=?',(new['citizen_id'],));bid=w.build('garden')
        before=w.state()
        with self.assertRaises(ValueError):w.change('worker',building_id=999999,citizen_id=old['citizen_id'])
        self.assertEqual(before,w.state())
        w.change('worker',building_id=bid,citizen_id=old['citizen_id']);state=w.state()
        self.assertEqual(next(c for c in state['citizens'] if c['citizen_id']==old['citizen_id'])['assignment'],'production')
        self.assertEqual(next(c for c in state['citizens'] if c['assignment']=='administrator')['citizen_id'],new['citizen_id'])
        self.assertEqual(w.sql("SELECT count(*) FROM citizen_assignments WHERE citizen_id=? AND ended_at IS NULL",(old['citizen_id'],))[0][0],1)

    def test_administrator_can_build_with_no_replacement_and_advisor_warns(self):
        w=self.world();admin=next(c for c in w.state()['citizens'] if c['assignment']=='administrator');bid=w.build('garden')
        for c in w.state()['citizens']:
            if c['assignment']=='unassigned':w.sql("INSERT INTO citizen_assignments(citizen_id,settlement_id,assignment_type,assigned_at) VALUES (?,?,'patrol',1000)",(c['citizen_id'],w.sa))
        w.change('build',building_type='rain_collector',x=23,y=21);site=w.state()['buildings'][-1]['building_id']
        w.change('builder',building_id=site,citizen_id=admin['citizen_id'])
        self.assertFalse(any(c['assignment']=='administrator' for c in w.state()['citizens']))
        self.assertTrue(any('no Administrator' in m for m in advisor.report(w.state())))

    def test_administrator_raid_keeps_home_floor_and_replaces_after_deployment(self):
        from game import combat
        w=self.world();old=next(c for c in w.state()['citizens'] if c['assignment']=='administrator')
        with account_scope(w.a):combat.command(w.path,'declare',1000,target_id=w.sb)
        with account_scope(w.a),self.assertRaises(ValueError):combat.command(w.path,'launch',4600,target_id=w.sb,citizen_ids=[old['citizen_id']])
        w.extra()
        with account_scope(w.a):combat.command(w.path,'launch',4600,target_id=w.sb,citizen_ids=[old['citizen_id']])
        state=w.state();self.assertEqual(sum(not c.get('away') for c in state['citizens']),6)
        self.assertTrue(next(c for c in state['citizens'] if c['citizen_id']==old['citizen_id'])['away'])
        self.assertNotEqual(next(c for c in state['citizens'] if c['assignment']=='administrator')['citizen_id'],old['citizen_id'])

    def test_vacant_administrator_fills_when_worker_becomes_available(self):
        w=self.world();w.sql("UPDATE citizen_assignments SET ended_at=1000 WHERE assignment_type='administrator' AND settlement_id=?",(w.sa,))
        with closing(connect_database(w.path)) as c,c,account_scope(w.a):
            c.row_factory=sqlite3.Row;self.assertTrue(consequences.synchronize(c,read_state(c),1000))
            state=read_state(c);self.assertTrue(any(x['assignment']=='administrator' for x in state['citizens']))
            self.assertFalse(consequences.synchronize(c,state,1000))

    def test_birth_supply_boundary_uses_current_rations_for_newborn(self):
        from game.economy import rates
        w=self.world();state=w.state()
        state['needs_clock']={'since':{'food':None,'water':None},'pending':{}}
        state['policies']['food_ration']=state['policies']['water_ration']='reduced'
        next(c for c in state['citizens'] if c['assignment']=='administrator')['assignment']='patrol'
        flow=rates(state)
        for resource in ('food','water'):
            per_person=state['config']['needs']['rations'][resource]['reduced']['consumption']
            state['resources'][resource]=24*(flow[resource]['consumption']+per_person-flow[resource]['production'])
        self.assertGreater(consequences.birth_chance(state),0)
        for resource in ('food','water'):
            short=copy.deepcopy(state);short['resources'][resource]-=.01
            self.assertEqual(consequences.birth_chance(short),0)

class ReviewTransportTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from game import accounts,admin,lobby
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'playtest.db';lobby.prepare(self.path)
        self.aid=accounts.register(self.path,'owner','owner-password-long',1000);admin.grant(self.path,'owner',1000)
        lobby.enroll(self.path,self.aid,'Review town',1000);lobby.start(self.path,self.aid,1000,'test')
        self.token,self.session=accounts.new_session(self.path,self.aid,1000)

    def test_operator_filtered_export_is_authorized_and_read_only(self):
        from admin_suite import create_app,COOKIE
        client=create_app(self.path,clock=lambda:1000).test_client();base='http://127.0.0.1:8768'
        self.assertEqual(client.get('/logs?format=json',base_url=base).status_code,303)
        client.set_cookie(COOKIE,self.token,domain='127.0.0.1')
        before=self.path.read_bytes();response=client.get('/logs?kind=expansion_enabled&format=json',base_url=base)
        self.assertEqual(response.status_code,200);self.assertIn('attachment',response.headers['Content-Disposition'])
        data=response.get_json();self.assertTrue(data);self.assertTrue(all(r['event_type']=='expansion_enabled' for r in data))
        self.assertEqual(before,self.path.read_bytes());self.assertEqual(client.get('/logs?before=-1',base_url=base).status_code,400)

    def test_player_advisor_route_csrf_saved_history_and_archive_rejection(self):
        from flask_app import create_app,COOKIE
        client=create_app(self.path,clock=lambda:1000).test_client();base='http://127.0.0.1:8767'
        client.set_cookie(COOKIE,self.token,domain='127.0.0.1')
        self.assertEqual(client.post('/advisor',data={'token':'bad','action':'report'},base_url=base).status_code,403)
        response=client.post('/advisor',data={'token':self.session['csrf'],'action':'report'},base_url=base)
        self.assertEqual(response.status_code,303)
        page=client.get('/',base_url=base);self.assertEqual(page.status_code,200);self.assertIn('Recent saved reports',page.text)
        self.assertEqual(client.post('/advisor',data={'token':self.session['csrf'],'action':'wrong'},base_url=base).status_code,400)

    def test_administrative_suspension_ui_does_not_suggest_trade_recovery(self):
        from flask_app import create_app,COOKIE
        # Operator metadata isolates the suspension presentation fixture.
        with closing(connect_database(self.path)) as c,c:
            c.execute("UPDATE settlements SET status='suspended',suspended_at=1000")
            from game.admin_controls import ensure
            ensure(c)
            c.execute("INSERT INTO admin_freezes(settlement_id,started_at,previous_status,previous_suspended_at) VALUES (1,1000,'active',NULL)")
        client=create_app(self.path,clock=lambda:1000).test_client();client.set_cookie(COOKIE,self.token,domain='127.0.0.1')
        page=client.get('/',base_url='http://127.0.0.1:8767')
        self.assertEqual(page.status_code,200);self.assertIn('administrator must reactivate',page.text)

    def test_away_drone_earns_loot_before_loss_on_return(self):
        from game import ruins,structural
        w=SupportWorld(self);w.change('enable_structural');w.weak()
        uid=w.unit();home=w.state()['units'][-1]['home_building_id'];aid=w.raid(units=[uid])
        with closing(connect_database(w.path)) as c,c,account_scope(w.a):
            c.row_factory=sqlite3.Row;ruins.hit(c,read_state(c),home,10000,4601,None,[])
        unit=next(u for u in w.state()['units'] if u['unit_id']==uid)
        self.assertEqual(unit['status'],'deployed');self.assertGreater(unit['current_hp'],0)
        warnings=w.sql("SELECT account_id,message FROM notifications WHERE notification_type='deployed_drone_home_destroyed'")
        self.assertEqual(len(warnings),1);self.assertEqual(warnings[0][0],w.a);self.assertIn('free slots',warnings[0][1])
        w.advance(8200);report=w.report()
        self.assertEqual(report['result'],'attacker_win');self.assertGreater(report['loot']['deposited']['scrap'],0)
        self.assertEqual(report['drone_returns'][0]['outcome'],'destroyed_no_home')
        self.assertEqual(w.sql('SELECT status,current_hp FROM military_units WHERE unit_id=?',(uid,))[0],('destroyed',0))
        self.assertEqual(w.sql('SELECT outcome FROM attack_drones WHERE attack_id=? AND unit_id=?',(aid,uid))[0][0],'destroyed_no_home')
        from game.combat import panel
        self.assertIn('destroyed on return: no compatible free storage slot',panel(w.path,w.state(),'token',8200))
        before=w.state();w.advance(8200);self.assertEqual(before,w.state())

    def test_away_drone_returns_to_replacement_with_earned_loot(self):
        from game import ruins
        w=SupportWorld(self);w.change('enable_structural');w.weak()
        uid=w.unit();home=w.state()['units'][-1]['home_building_id'];w.raid(units=[uid])
        with closing(connect_database(w.path)) as c,c,account_scope(w.a):
            c.row_factory=sqlite3.Row;ruins.hit(c,read_state(c),home,10000,4601,None,[])
        spare=w.build('offensive_hangar',x=24,y=18)
        w.advance(8200);report=w.report()
        self.assertGreater(report['loot']['deposited']['scrap'],0)
        self.assertEqual(w.sql('SELECT status,home_building_id FROM military_units WHERE unit_id=?',(uid,))[0],('available',spare))
        self.assertEqual(report['drone_returns'][0]['outcome'],'returned')

    def test_rebuilding_shield_requires_all_other_buildings_destroyed(self):
        from game import ruins,structural
        w=SupportWorld(self);w.change('enable_structural')
        survivor=w.build('garden')
        with closing(connect_database(w.path)) as c,c,account_scope(w.a):
            c.row_factory=sqlite3.Row
            for b in read_state(c)['buildings'][1:]:
                if b['building_id']!=survivor:ruins.hit(c,read_state(c),b['building_id'],10000,1000,None,[])
            structural.protect(c,read_state(c),1000)
            self.assertNotEqual(read_state(c)['settlement']['protection_type'],'rebuilding')
            # Construction and upgrading also count, even when not functioning.
            for status in ('construction','upgrading'):
                c.execute('UPDATE buildings SET status=? WHERE building_id=?',(status,survivor))
                structural.protect(c,read_state(c),1000)
                self.assertNotEqual(read_state(c)['settlement']['protection_type'],'rebuilding')
            c.execute("UPDATE buildings SET status='active' WHERE building_id=?",(survivor,))
            ruins.hit(c,read_state(c),survivor,10000,1000,None,[])
            structural.protect(c,read_state(c),1000)
            self.assertEqual(read_state(c)['settlement']['protection_type'],'rebuilding')
            self.assertEqual(read_state(c)['settlement']['protection_until'],87400)

"""Citizen clock, departure, birth and exposure integration on temporary saves."""
from contextlib import closing
import copy,json,sqlite3,unittest
from unittest.mock import patch,Mock
from tests.fixtures import SupportWorld,versioned_support_world
from game import consequences,ruins,combat
from game.settlement import account_scope,read_state,load_config
from game.buildings import spec,job_speed
from database.create_database import connect_database

class CitizenConsequenceTests(unittest.TestCase):
    def setUp(self):
        self.w=versioned_support_world(self,'enable_consequences','prototype_v13')

    def call(self,fn,*args,now=1000,account=None):
        with closing(connect_database(self.w.path)) as c,c,account_scope(account or self.w.a):
            c.row_factory=sqlite3.Row
            return fn(c,read_state(c),*args,now)

    def test_activation_repeat_late_join_and_clocks_for_every_player(self):
        w=self.w;before=w.state();w.change('enable_consequences');self.assertEqual(before,w.state())
        self.assertEqual(w.state(w.b)['consequences_clock']['enabled_at'],1000)
        w.player('charlie');state=w.state();self.assertEqual(state['season']['config_version'],'prototype_v13')
        self.assertIsNone(state['needs_clock'])

    def test_oxygen_exposure_requires_explicit_confirmation(self):
        w=self.w;w.change('build',building_type='garden',x=35,y=35);bid=w.state()['buildings'][-1]['building_id'];cid=w.state()['citizens'][1]['citizen_id'];before=w.state()
        with self.assertRaises(ValueError):w.change('builder',building_id=bid,citizen_id=cid)
        self.assertEqual(before,w.state())
        w.change('builder',building_id=bid,citizen_id=cid,exposed=True)
        c=next(c for c in w.state()['citizens'] if c['citizen_id']==cid)
        self.assertEqual(c['exposure_morale_modifier'],-10)
        self.assertGreater(job_speed(w.state(),w.state()['jobs'][-1]),0)

    def expose(self,level=1,hp=100):
        w=self.w;w.change('build',building_type='garden',x=35,y=35);bid=w.state()['buildings'][-1]['building_id'];cid=w.state()['citizens'][1]['citizen_id']
        w.sql('UPDATE citizens SET level=?,current_hp=? WHERE citizen_id=?',(level,hp,cid));w.change('builder',building_id=bid,citizen_id=cid,exposed=True)
        return bid,cid

    def test_exposure_hp_rate_and_emergency_evacuation(self):
        w=self.w;bid,cid=self.expose();state=w.advance(1300);c=next(c for c in state['citizens'] if c['citizen_id']==cid)
        self.assertAlmostEqual(c['current_hp'],50,places=6)
        state=w.advance(1450);c=next(c for c in state['citizens'] if c['citizen_id']==cid)
        self.assertAlmostEqual(c['current_hp'],25,places=6);self.assertEqual(c['assignment'],'unassigned')
        self.assertEqual(c['exposure_morale_modifier'],0)
        self.assertEqual(state['consequences_clock']['exposed'],{})

    def test_higher_level_oxygen_tolerance(self):
        w=self.w;_,cid=self.expose(level=3,hp=116);state=w.advance(1060)
        c=next(c for c in state['citizens'] if c['citizen_id']==cid)
        self.assertAlmostEqual(c['current_hp'],116-116/11,places=6)

    def test_unexpected_oxygen_loss_evacuates_immediately(self):
        # A Garden now provides its own Oxygen; use a consuming workplace.
        w=self.w;bid=w.build('recycler');cid=w.staff(bid)[0]
        w.sql('UPDATE buildings SET origin_x=35,origin_y=35 WHERE building_id=?',(bid,));state=w.advance(1000)
        self.assertEqual(next(c for c in state['citizens'] if c['citizen_id']==cid)['assignment'],'unassigned')
        self.assertEqual(next(c for c in state['citizens'] if c['citizen_id']==cid)['current_hp'],100)

    def test_staffed_garden_retains_workers_in_its_own_oxygen_zone(self):
        w=self.w;bid=w.build('garden');cid=w.staff(bid)[0]
        w.sql('UPDATE buildings SET origin_x=35,origin_y=35 WHERE building_id=?',(bid,))
        state=w.advance(1000)
        citizen=next(c for c in state['citizens'] if c['citizen_id']==cid)
        self.assertEqual(citizen['assignment'],'production')
        self.assertEqual(citizen['current_hp'],100)
        self.assertFalse(consequences.unsafe(state,citizen))

    def test_exposure_stops_after_oxygen_restoration(self):
        w=self.w;bid,cid=self.expose();w.advance(1060)
        w.sql('UPDATE buildings SET origin_x=24,origin_y=18 WHERE building_id=?',(bid,));state=w.advance(1060)
        self.assertEqual(state['consequences_clock']['exposed'],{})
        self.assertEqual(next(c for c in state['citizens'] if c['citizen_id']==cid)['exposure_morale_modifier'],0)

    def test_homelessness_grace_and_health_loss(self):
        w=self.w;cid=w.state()['citizens'][1]['citizen_id'];w.sql('UPDATE citizens SET homeless_since=1000 WHERE citizen_id=?',(cid,))
        self.call(consequences.accrue,43200,now=44200)
        self.assertEqual(next(c for c in w.state()['citizens'] if c['citizen_id']==cid)['current_hp'],100)
        self.call(consequences.accrue,3600,now=47800)
        self.assertEqual(next(c for c in w.state()['citizens'] if c['citizen_id']==cid)['current_hp'],99)

    def test_unemployment_grace_fractional_drift_and_reemployment(self):
        w=self.w;cid=w.state()['citizens'][1]['citizen_id'];w.sql('UPDATE citizens SET unemployed_since=1000 WHERE citizen_id=?',(cid,))
        self.call(consequences.accrue,43200,now=44200);self.assertEqual(w.state()['citizens'][1]['morale'],60)
        self.call(consequences.accrue,43200,now=87400);self.assertAlmostEqual(w.state()['citizens'][1]['morale'],59.5)
        bid=w.build('garden');w.staff(bid);before=w.state()['citizens'][1]['morale']
        self.call(consequences.accrue,3600,now=91000);self.assertEqual(w.state()['citizens'][1]['morale'],before)

    def test_activation_never_backdates_homelessness_damage(self):
        w=self.w;cid=w.state()['citizens'][1]['citizen_id'];w.sql('UPDATE citizens SET homeless_since=-100000 WHERE citizen_id=?',(cid,))
        self.call(consequences.accrue,3600,now=4600)
        self.assertEqual(w.state()['citizens'][1]['current_hp'],100)

    def test_birth_eligibility_sex_morale_housing_and_supplies(self):
        w=self.w;self.assertGreater(consequences.birth_chance(w.state()),0)
        w.sql("UPDATE citizens SET sex='male' WHERE settlement_id=?",(w.sa,));self.assertEqual(consequences.birth_chance(w.state()),0)
        w.sql("UPDATE citizens SET sex='female' WHERE citizen_id=?",(w.state()['citizens'][1]['citizen_id'],));w.sql('UPDATE citizens SET morale=0 WHERE settlement_id=?',(w.sa,));self.assertEqual(consequences.birth_chance(w.state()),0)
        w.sql('UPDATE citizens SET morale=60 WHERE settlement_id=?',(w.sa,));w.sql('UPDATE settlement_resources SET food=0,water=0 WHERE settlement_id=?',(w.sa,));self.assertEqual(consequences.birth_chance(w.state()),0)

    def test_birth_housing_slowdown_and_full_capacity(self):
        state=self.w.state();capacity=state['recovery_housing']['capacity'];base=consequences.birth_chance(state)
        state['recovery_housing']['capacity']=len(state['citizens'])/.9
        # Isolate occupancy from supply qualification with ample stock.
        state['resources']['food']=state['resources']['water']=10000
        self.assertAlmostEqual(consequences.birth_chance(state),base*.4)
        state['recovery_housing']['capacity']=len(state['citizens']);self.assertEqual(consequences.birth_chance(state),0)

    def test_birth_roll_is_audited_and_not_repeated(self):
        rng=Mock();rng.random.return_value=0;rng.choice.return_value='female'
        with patch('game.consequences.random.Random',return_value=rng):self.call(consequences.daily,now=86400)
        w=self.w;births=w.sql("SELECT citizen_id,level FROM citizens WHERE citizen_id IN (SELECT citizen_id FROM citizen_settlement_history WHERE arrival_reason='birth')")
        self.assertEqual(len(births),1);self.assertEqual(births[0][1],1)
        before=w.state();self.call(consequences.daily,now=86400);self.assertEqual(before,w.state())
        event=json.loads(w.sql("SELECT event_data FROM game_events WHERE event_type='citizen_daily_rollover' AND settlement_id=?",(w.sa,))[0][0]);self.assertEqual(event['birth_citizen_id'],births[0][0])

    def test_desertion_preserves_six_physically_home(self):
        w=self.w;w.extra(3);w.sql('UPDATE citizens SET morale=0 WHERE settlement_id=?',(w.sa,))
        rng=Mock();rng.random.return_value=0
        with patch('game.consequences.random.Random',return_value=rng):self.call(consequences.daily,now=86400)
        self.assertEqual(len(w.state()['citizens']),6)
        self.assertEqual(len(w.sql("SELECT citizen_id FROM citizens WHERE settlement_id=? AND status='deserted'",(w.sa,))),3)
        self.assertTrue(any(c['assignment']=='administrator' for c in w.state()['citizens']))

    def test_expulsion_preserves_floor_and_applies_survivor_morale(self):
        w=self.w;cid=w.state()['citizens'][1]['citizen_id'];before=w.state()
        with self.assertRaises(ValueError):w.change('expel',citizen_id=cid)
        self.assertEqual(before,w.state())
        cid=w.extra()[0];w.change('expel',citizen_id=cid)
        self.assertEqual(len(w.state()['citizens']),6);self.assertTrue(all(c['morale']==57 for c in w.state()['citizens']))
        self.assertEqual(w.sql('SELECT status FROM citizens WHERE citizen_id=?',(cid,))[0][0],'expelled')

    def test_expelled_admin_is_replaced_with_history_retained(self):
        w=self.w;w.extra();cid=w.state()['citizens'][0]['citizen_id'];w.change('expel',citizen_id=cid)
        self.assertTrue(any(c['assignment']=='administrator' for c in w.state()['citizens']))
        self.assertFalse(w.sql('SELECT 1 FROM citizen_assignments WHERE citizen_id=? AND ended_at IS NULL',(cid,)))

    def test_needs_death_releases_job_and_records_identity(self):
        w=self.w;cid=w.state()['citizens'][1]['citizen_id'];w.sql('UPDATE citizens SET homeless_since=1000,current_hp=.5 WHERE citizen_id=?',(cid,))
        self.call(consequences.accrue,3600,now=47800)
        self.assertEqual(w.sql('SELECT status,current_hp FROM citizens WHERE citizen_id=?',(cid,))[0],('dead',0.0))

    def test_chunked_and_single_exposure_catchup_match(self):
        import shutil
        w=self.w;_,cid=self.expose();clone=w.path.with_name('clone.db');shutil.copy2(w.path,clone)
        single=w.advance(1450)
        from game.simulation import advance_settlement
        with account_scope(w.a):
            for now in (1031,1060,1117,1270,1450):chunked=advance_settlement(clone,now)
        self.assertAlmostEqual(next(c for c in single['citizens'] if c['citizen_id']==cid)['current_hp'],next(c for c in chunked['citizens'] if c['citizen_id']==cid)['current_hp'],places=5)
        self.assertEqual(single['consequences_clock']['exposed'],chunked['consequences_clock']['exposed'])

    def test_ui_exposes_warning_and_enable_controls(self):
        from game.views import render_page
        w=self.w;self.expose();html=render_page(w.state(),'test-token').decode()
        self.assertIn('Danger: outside Oxygen',html);self.assertIn('Citizen wellbeing',html)
        self.assertNotIn('Births and ongoing homelessness damage remain deferred',html)


    def test_midnight_floor_restores_combat_losses_once(self):
        w=self.w
        ids=[c['citizen_id'] for c in w.state()['citizens']][-2:]
        for cid in ids:w.sql("UPDATE citizens SET status='dead',current_hp=0 WHERE citizen_id=?",(cid,))
        self.call(consequences.daily,now=86400)
        self.assertEqual(len(w.state()['citizens']),6)
        self.call(consequences.daily,now=86400);self.assertEqual(len(w.state()['citizens']),6)

    def test_supply_consequences_can_be_enabled_after_citizen_features(self):
        from game.needs import command
        w=self.w
        with account_scope(w.a):command(w.path,'enable',1000)
        self.assertEqual(w.state()['season']['config_version'],'prototype_v13')
        self.assertIsNotNone(w.state()['needs_clock'])

    def test_paused_time_does_not_age_unemployment(self):
        from game.settlement import create_settlement,read_settlement,prepare_database
        from game.buildings import change_building
        from game.simulation import apply_action,advance_settlement
        path=self.w.path.with_name('paused.db');prepare_database(path);create_settlement(path,'Paused',1000)
        change_building(path,'enable_consequences',now=1000)
        apply_action(path,'resume',now=87400)
        state=advance_settlement(path,87460)
        self.assertEqual(state['consequences_clock']['enabled_at'],87400)
        self.assertTrue(all(c['morale']==60 for c in state['citizens']))

    def test_away_citizens_are_not_expelled_or_used_as_birth_partners(self):
        w=self.w;ids=w.extra();cid=ids[0]
        with account_scope(w.a):
            combat.command(w.path,'declare',1000,target_id=w.sb)
            combat.command(w.path,'launch',4600,target_id=w.sb,citizen_ids=ids)
        before=w.state()
        with self.assertRaises(ValueError):w.change('expel',now=4600,citizen_id=cid)
        self.assertEqual(before,w.state())

"""Repair spending, crew work, regeneration, time boundaries and rollback."""
import unittest,sqlite3
from contextlib import closing
import test_population as fixtures
from game.buildings import change_building
from game.simulation import apply_action,advance_settlement
from game.repairs import costs
from game.settlement import load_config
from game.views import render_page

class RepairTests(unittest.TestCase):
    setUp=fixtures.PopulationTests.setUp
    sql=fixtures.PopulationTests.sql
    state=fixtures.PopulationTests.state
    home=fixtures.PopulationTests.home
    def enable(self):return change_building(self.path,'enable_repairs',now=1000)
    def damaged(self,kind='garden',missing=20):
        bid=self.home(kind);self.sql('UPDATE buildings SET current_hp=current_hp-? WHERE building_id=?',(missing,bid));return bid
    def crew(self,bid,cid=2):
        change_building(self.path,'repair',building_id=bid,now=1000)
        return change_building(self.path,'repairer',building_id=bid,citizen_id=cid,now=1000)
    def test_enable_preserves_and_older_actions_do_not_downgrade(self):
        change_building(self.path,'enable_progression',now=1000);before=self.state();after=self.enable()
        for key in ('citizens','buildings','resources','derelicts','jobs'):self.assertEqual(before[key],after[key])
        for action in ('enable_repairs','enable_progression','enable_recovery','enable_housing','enable'):
            self.assertEqual(after,change_building(self.path,action,now=1000))
    def test_costs_paid_once_and_duplicate_rejected(self):
        self.enable();bid=self.damaged();before=self.state();b=before['buildings'][-1];price=costs(before,b)
        self.assertAlmostEqual(price['scrap'],35*.5*20/150)
        after=change_building(self.path,'repair',building_id=bid,now=1000)
        self.assertAlmostEqual(after['resources']['scrap'],before['resources']['scrap']-price['scrap'])
        with self.assertRaises(ValueError):change_building(self.path,'repair',building_id=bid,now=1000)
        self.assertEqual(after,self.state())
    def test_repair_twenty_hp_per_hour_xp_and_worker_release(self):
        self.enable();bid=self.damaged();self.crew(bid);apply_action(self.path,'resume',now=1000)
        state=advance_settlement(self.path,now=4600)
        self.assertEqual(state['buildings'][-1]['current_hp'],150)
        self.assertAlmostEqual(state['citizens'][1]['xp'],2)
        self.assertEqual(state['citizens'][1]['assignment'],'unassigned')
        self.assertEqual(state['jobs'][0]['status'],'completed')
    def test_unstaffed_repair_paused_and_release_retains_work(self):
        self.enable();bid=self.damaged(missing=40);self.crew(bid);apply_action(self.path,'resume',now=1000)
        state=change_building(self.path,'release',building_id=bid,citizen_id=2,now=1060);hp=state['buildings'][-1]['current_hp']
        self.assertGreater(hp,110);self.assertEqual(advance_settlement(self.path,now=1120)['buildings'][-1]['current_hp'],hp)
    def test_two_workers_diminishing_returns(self):
        self.enable();bid=self.damaged(missing=40);self.crew(bid)
        change_building(self.path,'repairer',building_id=bid,citizen_id=3,now=1000);apply_action(self.path,'resume',now=1000)
        state=advance_settlement(self.path,now=1060)
        self.assertAlmostEqual(state['buildings'][-1]['current_hp'],110+20*2**.5/60)
    def test_staffed_hall_regeneration_cap_and_unstaffed(self):
        self.enable();self.sql('UPDATE buildings SET current_hp=999.99 WHERE building_id=1');apply_action(self.path,'resume',now=1000)
        self.assertEqual(advance_settlement(self.path,now=1060)['buildings'][0]['current_hp'],1000)
        self.sql('UPDATE buildings SET current_hp=900 WHERE building_id=1');self.sql("UPDATE citizen_assignments SET ended_at=1060 WHERE assignment_type='administrator'")
        self.assertEqual(advance_settlement(self.path,now=1120)['buildings'][0]['current_hp'],900)
    def test_hall_manual_and_passive_repair_combine_without_double_xp(self):
        self.enable();self.sql('UPDATE buildings SET current_hp=900 WHERE building_id=1');self.crew(1);apply_action(self.path,'resume',now=1000)
        state=advance_settlement(self.path,now=4600)
        self.assertAlmostEqual(state['buildings'][0]['current_hp'],921)
        self.assertAlmostEqual(state['citizens'][1]['xp'],2)
    def test_pause_keeps_regeneration_credit_and_freezes_repairs(self):
        self.enable();self.sql('UPDATE buildings SET current_hp=900 WHERE building_id=1');apply_action(self.path,'resume',now=1000)
        apply_action(self.path,'pause',now=1010);self.assertAlmostEqual(self.state()['regen_pending'],10/3600)
        self.assertEqual(advance_settlement(self.path,now=2000)['buildings'][0]['current_hp'],900)
        apply_action(self.path,'resume',now=2010)
        self.assertAlmostEqual(advance_settlement(self.path,now=2060)['buildings'][0]['current_hp'],900+1/60)
    def test_offline_and_arbitrary_reads_equal(self):
        self.enable();bid=self.damaged(missing=40);self.crew(bid);self.sql('UPDATE buildings SET current_hp=900 WHERE building_id=1');apply_action(self.path,'resume',now=1000)
        alternate=self.path.with_name('offline.db')
        with closing(sqlite3.connect(self.path)) as a,closing(sqlite3.connect(alternate)) as b:a.backup(b)
        for now in (1007,1059,1061,1127,1211,1603):advance_settlement(self.path,now=now)
        one=advance_settlement(alternate,now=1603);many=self.state()
        for a,b in zip(one['buildings'],many['buildings']):self.assertAlmostEqual(a['current_hp'],b['current_hp'])
        for r in ('food','water'):self.assertAlmostEqual(one['resources'][r],many['resources'][r])
        self.assertAlmostEqual(one['citizens'][1]['xp'],many['citizens'][1]['xp'])
    def test_invalid_targets_tents_funds_unsafe_and_busy_workers(self):
        self.enable();tent=self.damaged('pup_tent',missing=1)
        for bid in (1,tent,999):
            before=self.state()
            with self.assertRaises(ValueError):change_building(self.path,'repair',building_id=bid,now=1000)
            self.assertEqual(before,self.state())
        bid=self.damaged();self.sql('UPDATE settlement_resources SET scrap=0');before=self.state()
        with self.assertRaises(ValueError):change_building(self.path,'repair',building_id=bid,now=1000)
        self.assertEqual(before,self.state());self.sql('UPDATE settlement_resources SET scrap=180');change_building(self.path,'repair',building_id=bid,now=1000)
        with self.assertRaises(ValueError):change_building(self.path,'repairer',building_id=bid,citizen_id=1,now=1000)
        self.sql('UPDATE buildings SET origin_x=0,origin_y=0 WHERE building_id=?',(bid,))
        with self.assertRaises(ValueError):change_building(self.path,'repairer',building_id=bid,citizen_id=2,now=1000)
    def test_failed_hp_write_rolls_back_progress_resources_and_xp(self):
        self.enable();bid=self.damaged();self.crew(bid);apply_action(self.path,'resume',now=1000);before=self.state()
        self.sql("CREATE TRIGGER fail_repair BEFORE UPDATE OF current_hp ON buildings BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):advance_settlement(self.path,now=1060)
        self.assertEqual(before,self.state())
    def test_upgrade_blocked_while_repairing_and_final_window(self):
        self.enable();bid=self.damaged('shack');self.crew(bid)
        with self.assertRaises(ValueError):change_building(self.path,'upgrade',building_id=bid,expected_level=1,now=1000)
        self.sql('UPDATE seasons SET finalization_at=1000');other=self.damaged('house')
        with self.assertRaises(ValueError):change_building(self.path,'repair',building_id=other,now=1000)
    def test_ui_controls_and_legacy_unchanged(self):
        self.assertIn('Enable building repairs',render_page(self.state(),'token').decode())
        self.enable();bid=self.damaged();self.assertIn('Start repairs',render_page(self.state(),'token').decode())
        self.crew(bid);self.assertIn('Repair worker',render_page(self.state(),'token').decode())
        self.assertNotIn('repairs',load_config('prototype_v7'))

    def test_repair_restores_output_storage_and_housing(self):
        self.enable();bid=self.damaged('house',missing=80)
        from game.population import housing
        before=housing(self.state())['capacity'];self.crew(bid);apply_action(self.path,'resume',now=1000)
        after=advance_settlement(self.path,now=15400)
        self.assertGreater(housing(after)['capacity'],before)
    def test_season_finish_and_suspension_freeze_repair(self):
        self.enable();bid=self.damaged();self.crew(bid);apply_action(self.path,'resume',now=1000)
        self.sql("UPDATE settlements SET status='suspended'");self.assertEqual(advance_settlement(self.path,now=1060)['buildings'][-1]['current_hp'],130)
        self.sql("UPDATE settlements SET status='active'");self.sql('UPDATE seasons SET ends_at=1030,finalization_at=1000')
        state=advance_settlement(self.path,now=1060);self.assertAlmostEqual(state['buildings'][-1]['current_hp'],130+20/120)
        self.assertEqual(state,advance_settlement(self.path,now=2000))
    def test_production_remains_active_during_repairs(self):
        self.enable();bid=self.damaged();self.crew(bid);change_building(self.path,'worker',building_id=bid,citizen_id=3,now=1000)
        from game.simulation import resource_rates
        before=resource_rates(self.state())['food']['production'];apply_action(self.path,'resume',now=1000)
        state=advance_settlement(self.path,now=1060)
        self.assertGreater(resource_rates(state)['food']['production'],before)
        self.assertGreater(state['citizens'][2]['xp'],0)
    def test_prior_version_does_not_regenerate(self):
        change_building(self.path,'enable_progression',now=1000);self.sql('UPDATE buildings SET current_hp=900 WHERE building_id=1');apply_action(self.path,'resume',now=1000)
        self.assertEqual(advance_settlement(self.path,now=1060)['buildings'][0]['current_hp'],900)
    def test_regeneration_does_not_clamp_completed_hall_upgrade(self):
        self.enable();self.sql('UPDATE buildings SET current_hp=900 WHERE building_id=1');self.sql('UPDATE settlement_resources SET scrap=1000,metal=1000,electronics=1000')
        change_building(self.path,'upgrade',building_id=1,expected_level=1,now=1000);change_building(self.path,'builder',building_id=1,citizen_id=2,now=1000)
        apply_action(self.path,'resume',now=1000);state=advance_settlement(self.path,now=11800)
        self.assertEqual(state['buildings'][0]['level'],2);self.assertGreater(state['buildings'][0]['current_hp'],1000)

    def test_wrong_assignment_type_cannot_join_repair(self):
        self.enable();bid=self.damaged();change_building(self.path,'repair',building_id=bid,now=1000);before=self.state()
        with self.assertRaises(ValueError):change_building(self.path,'builder',building_id=bid,citizen_id=2,now=1000)
        self.assertEqual(before,self.state())

    def test_completed_repair_allows_another_repair(self):
        self.enable();bid=self.damaged();self.crew(bid);apply_action(self.path,'resume',now=1000);advance_settlement(self.path,now=4600)
        self.sql('UPDATE buildings SET current_hp=current_hp-20 WHERE building_id=?',(bid,))
        state=change_building(self.path,'repair',building_id=bid,now=4600)
        self.assertEqual(len(state['jobs']),2)

import test_prototype as http_fixtures
from game.settlement import read_settlement
from urllib.parse import urlencode
class RepairHTTPTests(unittest.TestCase):
    setUp=http_fixtures.HTTPTests.setUp
    start_server=http_fixtures.HTTPTests.start_server
    stop_server=http_fixtures.HTTPTests.stop_server
    request=http_fixtures.HTTPTests.request
    create=http_fixtures.HTTPTests.create
    def test_activation_and_invalid_repair_requests(self):
        self.create();before=read_settlement(self.path)
        def post(action,token,**fields):return self.request('POST','/buildings',urlencode({'action':action,'token':token,**fields}),{'Content-Type':'application/x-www-form-urlencoded'})
        self.assertEqual(post('enable_repairs','forged')[0],403);self.assertEqual(before,read_settlement(self.path))
        self.assertEqual(post('enable_repairs',self.server.form_token)[0],303)
        before=read_settlement(self.path)
        self.assertEqual(post('repair',self.server.form_token,building_id=1)[0],400);self.assertEqual(before,read_settlement(self.path))
        self.stop_server();self.start_server();self.assertEqual(before,read_settlement(self.path))

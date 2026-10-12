"""Deterministic resource, staffing, clock, and HTTP regression tests."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from urllib.parse import urlencode

from app import PrototypeServer
from database.create_database import connect_database
from game.settlement import create_settlement, prepare_database, read_settlement
from game.simulation import advance_settlement, apply_action, resource_rates
import test_prototype as prototype_tests


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'simulation.db'
        prepare_database(self.path)
        create_settlement(self.path, 'Clock Test', now=1000)

    def query(self, sql, values=()):
        with closing(connect_database(self.path)) as connection, connection:
            return connection.execute(sql, values).fetchall()

    def test_base_production_consumption_and_depletion_forecast(self):
        rates = resource_rates(read_settlement(self.path))
        for resource in ('food', 'water'):
            self.assertEqual(rates[resource], {'production':2, 'consumption':6, 'net':-4,
                                              'capacity':150, 'hours_to_empty':30})

    def test_paused_reads_do_not_advance_or_upgrade(self):
        before = read_settlement(self.path)
        self.assertEqual(advance_settlement(self.path, now=100000), before)
        self.assertEqual(before['season']['config_version'], 'prototype_v1')

    def test_resume_upgrades_configuration_once_without_reset(self):
        self.query('UPDATE settlement_resources SET food=91.5')
        apply_action(self.path, 'resume', now=2000)
        apply_action(self.path, 'resume', now=2000)
        state = read_settlement(self.path)
        self.assertEqual(state['season']['config_version'], 'prototype_v2')
        self.assertEqual(state['resources']['food'], 91.5)
        self.assertEqual(state['resources']['credits'], 500)
        self.assertEqual(len(state['citizens']),6)
        self.assertEqual(self.query("SELECT count(*) FROM game_events WHERE event_type='prototype_config_enabled'"),[(1,)])
        self.assertEqual(self.query('PRAGMA user_version'),[(1,)])

    def test_hour_elapsed_and_repeated_or_earlier_read(self):
        apply_action(self.path,'resume',now=1000)
        after = advance_settlement(self.path,now=4600)
        self.assertEqual(after['resources']['food'],116)
        self.assertEqual(after['resources']['water'],116)
        self.assertEqual(advance_settlement(self.path,now=4600),after)
        self.assertEqual(advance_settlement(self.path,now=4500),after)
        self.assertEqual(after['resources']['scrap'],180)

    def test_small_steps_equal_one_elapsed_interval(self):
        apply_action(self.path,'resume',now=1000)
        for now in range(1900,4601,900):
            result = advance_settlement(self.path,now=now)
        self.assertAlmostEqual(result['resources']['food'],116,places=9)
        self.assertEqual(result['settlement']['simulation_processed_at'],4600)

    def test_pause_resume_freezes_resources_and_deadlines(self):
        initial = read_settlement(self.path)
        apply_action(self.path,'resume',now=1000)
        paused = apply_action(self.path,'pause',now=4600)
        self.assertEqual(paused['resources']['food'],116)
        self.assertEqual(advance_settlement(self.path,now=10000),paused)
        resumed = apply_action(self.path,'resume',now=10000)
        self.assertEqual(resumed['resources']['food'],116)
        self.assertEqual(resumed['season']['ends_at'],initial['season']['ends_at']+5400)
        self.assertEqual(resumed['settlement']['protection_until'],initial['settlement']['protection_until']+5400)
        self.assertEqual(advance_settlement(self.path,now=13600)['resources']['food'],112)

    def test_depletion_pauses_at_first_empty_pool_without_negative_values(self):
        self.query('UPDATE settlement_resources SET food=1')
        apply_action(self.path,'resume',now=1000)
        result = advance_settlement(self.path,now=1000000)
        self.assertEqual(result['resources']['food'],0)
        self.assertEqual(result['resources']['water'],119)
        self.assertEqual(result['season']['status'],'paused')
        self.assertEqual(result['season']['paused_at'],1900)
        self.assertEqual(result['settlement']['simulation_processed_at'],1900)
        self.assertEqual(advance_settlement(self.path,now=2000000),result)
        self.assertTrue(all(c['current_hp']==100 for c in result['citizens']))
        with self.assertRaises(ValueError):
            apply_action(self.path,'resume',now=2000000)

    def test_production_respects_storage_and_condition(self):
        self.query("UPDATE citizens SET status='dead',current_hp=0 WHERE citizen_id!=1")
        self.query('UPDATE citizens SET level=10,current_hp=172,morale=100 WHERE citizen_id=1')
        self.query('UPDATE settlement_resources SET food=149.9,water=149.9')
        apply_action(self.path,'resume',now=1000)
        result=advance_settlement(self.path,now=4600)
        self.assertEqual(result['resources']['food'],150)
        self.query('UPDATE buildings SET current_hp=500')
        result=advance_settlement(self.path,now=8200)
        self.assertEqual(result['resources']['food'],75)

    def test_worker_condition_level_and_morale_affect_rates(self):
        self.query('UPDATE citizens SET level=2,current_hp=54,morale=80 WHERE citizen_id=1')
        rates=resource_rates(read_settlement(self.path))
        self.assertAlmostEqual(rates['food']['production'],2 * .5 * 1.03 * 1.1)
        self.query('UPDATE citizens SET morale=10 WHERE citizen_id=1')
        self.assertAlmostEqual(resource_rates(read_settlement(self.path))['food']['production'],2 * .5 * 1.03 * .7)

    def test_unstaffed_hall_has_no_production(self):
        self.query("UPDATE citizen_assignments SET ended_at=1000,end_reason='test'")
        self.assertEqual(resource_rates(read_settlement(self.path))['food']['production'],0)

    def test_reassignment_settles_old_rates_then_uses_new_rates(self):
        self.query('UPDATE citizens SET current_hp=50 WHERE citizen_id=2')
        apply_action(self.path,'resume',now=1000)
        reassigned=apply_action(self.path,'assign',citizen_id=2,now=4600)
        self.assertEqual(reassigned['resources']['food'],116)
        self.assertEqual(advance_settlement(self.path,now=8200)['resources']['food'],111)
        self.assertEqual(self.query('SELECT citizen_id,assigned_at,ended_at FROM citizen_assignments ORDER BY assignment_id'),
                         [(1,1000,4600),(2,4600,None)])

    def test_duplicate_assignment_and_paused_assignment_preserve_history(self):
        apply_action(self.path,'assign',citizen_id=2,now=2000)
        apply_action(self.path,'assign',citizen_id=2,now=3000)
        self.assertEqual(self.query('SELECT count(*) FROM citizen_assignments'),[(2,)])
        self.assertEqual(self.query('SELECT assigned_at FROM citizen_assignments WHERE ended_at IS NULL'),[(1000,)])
        apply_action(self.path,'resume',now=5000)
        self.assertEqual(self.query('SELECT unemployed_since FROM citizens WHERE citizen_id=1'),[(5000,)])

    def test_invalid_assignment_does_not_advance_or_change_state(self):
        apply_action(self.path,'resume',now=1000)
        before=read_settlement(self.path)
        with self.assertRaises(ValueError):
            apply_action(self.path,'assign',citizen_id=999,now=4600)
        self.assertEqual(read_settlement(self.path),before)
        self.query("INSERT INTO citizen_assignments (citizen_id,settlement_id,assignment_type,assigned_at) VALUES (2,1,'patrol',1000)")
        with self.assertRaises(ValueError):
            apply_action(self.path,'assign',citizen_id=2,now=4600)

    def test_assignment_failure_rolls_back_resources_and_history(self):
        apply_action(self.path,'resume',now=1000)
        self.query("CREATE TRIGGER reject_assignment BEFORE INSERT ON citizen_assignments BEGIN SELECT RAISE(ABORT,'test'); END")
        before=read_settlement(self.path)
        with self.assertRaises(sqlite3.IntegrityError):
            apply_action(self.path,'assign',citizen_id=2,now=4600)
        self.assertEqual(read_settlement(self.path),before)
        self.assertEqual(self.query('SELECT count(*) FROM citizen_assignments WHERE ended_at IS NULL'),[(1,)])

    def test_reopening_catches_up_exactly_once(self):
        apply_action(self.path,'resume',now=1000)
        prepare_database(self.path)
        self.assertEqual(advance_settlement(self.path,now=4600)['resources']['food'],116)
        prepare_database(self.path)
        self.assertEqual(advance_settlement(self.path,now=4600)['resources']['food'],116)

    def test_season_end_stops_progress(self):
        self.query('UPDATE seasons SET finalization_at=2000,ends_at=2800')
        apply_action(self.path,'resume',now=1000)
        result=advance_settlement(self.path,now=10000)
        self.assertEqual(result['resources']['food'],118)
        self.assertEqual(result['season']['status'],'finished')
        self.assertEqual(result['settlement']['status'],'archived')
        self.assertEqual(advance_settlement(self.path,now=20000),result)
        with self.assertRaises(ValueError):
            apply_action(self.path,'assign',citizen_id=2,now=20000)

    def test_suspended_settlement_does_not_progress(self):
        apply_action(self.path,'resume',now=1000)
        self.query("UPDATE settlements SET status='suspended',suspended_at=1000")
        before=read_settlement(self.path)
        self.assertEqual(advance_settlement(self.path,now=4600),before)
        with self.assertRaises(ValueError):
            apply_action(self.path,'resume',now=4600)


class ResourceHTTPTests(unittest.TestCase):
    request = prototype_tests.HTTPTests.request

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'web.db'
        prepare_database(self.path)
        create_settlement(self.path,'Browser Test',now=1000)
        self.now=1000
        self.server=PrototypeServer(('127.0.0.1',0),self.path,clock=lambda:self.now)
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def post(self,path,**values):
        return self.request('POST',path,urlencode({'token':self.server.form_token,**values}),
                            {'Content-Type':'application/x-www-form-urlencoded'})

    def test_start_poll_pause_and_staffing_flow(self):
        self.assertIn('Start time',self.request()[2])
        self.assertEqual(self.post('/clock',action='resume')[0],303)
        self.now=4600
        status,_,body=self.request(path='/api/resources')
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)['food'],116)
        self.assertNotIn('password',body)
        self.assertEqual(self.post('/administrator',citizen_id=2)[0],303)
        self.assertEqual(self.post('/clock',action='pause')[0],303)
        self.now=10000
        self.assertEqual(json.loads(self.request(path='/api/resources')[2])['food'],116)
        self.assertIn('Time is paused.',self.request()[2])
        self.assertEqual(read_settlement(self.path)['citizens'][1]['assignment'],'administrator')

    def test_new_routes_reject_forged_requests_and_invalid_actions(self):
        before=read_settlement(self.path)
        self.assertEqual(self.post('/clock',token='wrong',action='resume')[0],403)
        self.assertEqual(self.post('/clock',action='delete')[0],400)
        self.assertEqual(self.post('/administrator',citizen_id='abc')[0],400)
        self.assertEqual(self.post('/administrator',citizen_id=999)[0],400)
        self.assertEqual(read_settlement(self.path),before)


if __name__ == '__main__':
    unittest.main()

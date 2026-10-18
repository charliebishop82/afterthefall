"""Background updates must be fair, bounded, stoppable and activity-neutral."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from threading import Lock
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from database.create_database import connect_database
from game import background, admin_controls
from tests.fixtures import SupportWorld, fixed_map_seed


class BackgroundTests(unittest.TestCase):
    def world(self):
        with fixed_map_seed():w=SupportWorld(self)
        w.change('enable_consequences')
        return w

    def coordinator(self,w,now=1200):
        worker=background.Coordinator(w.path,Lock(),clock=lambda:now,
                                      log_path=Path(w.tmp.name)/'background.jsonl')
        self.addCleanup(worker.close_log)
        worker.last_report=time.monotonic()
        return worker

    def test_updates_without_login_and_does_not_renew_offline_allowance(self):
        w=self.world();worker=self.coordinator(w)
        before=w.sql('SELECT last_active_at FROM settlement_activity WHERE settlement_id=?',(w.sa,))
        result=worker.run_once()
        self.assertIsNotNone(result)
        self.assertGreater(w.state()['settlement']['simulation_processed_at'],1000)
        self.assertEqual(w.sql('SELECT last_active_at FROM settlement_activity WHERE settlement_id=?',(w.sa,)),before)
        self.assertTrue(worker.log_path.exists())

    def test_rotates_between_pending_settlements_instead_of_starving_one(self):
        w=self.world();worker=self.coordinator(w)
        with patch('game.background.catchup.step',return_value={'status':'catching_up'}) as step:
            worker.run_once();worker.run_once();worker.run_once()
        self.assertEqual([call.args[1] for call in step.call_args_list],[w.a,w.b,w.a])

    def test_does_not_wait_on_foreground_gate_or_sample_clock_before_it(self):
        w=self.world();worker=self.coordinator(w)
        worker.clock=MagicMock(return_value=1200)
        worker.gate.acquire()
        try:
            with patch('game.background.catchup.step') as step:
                self.assertIsNone(worker.run_once())
                step.assert_not_called();worker.clock.assert_not_called()
        finally:worker.gate.release()

    def test_failed_player_batch_releases_gate_and_next_player_can_update(self):
        w=self.world();worker=self.coordinator(w)
        with patch('game.background.catchup.step',side_effect=[sqlite3.OperationalError('locked'),{'status':'ready'}]) as step:
            with self.assertRaises(sqlite3.OperationalError):worker.run_once()
            self.assertEqual(worker.run_once()['status'],'ready')
        self.assertEqual([call.args[1] for call in step.call_args_list],[w.a,w.b])

    def test_pause_freeze_and_disabled_accounts_are_respected(self):
        w=self.world()
        with closing(connect_database(w.path)) as c,c:
            admin_controls.ensure(c)
            c.execute("INSERT INTO admin_freezes VALUES (?,1000,'active',NULL)",(w.sa,))
            c.execute('UPDATE accounts SET is_active=0 WHERE account_id=?',(w.b,))
        self.assertEqual(background.pending(w.path,1200),[])
        w.sql('DELETE FROM admin_freezes');w.sql('UPDATE accounts SET is_active=1')
        w.sql("UPDATE seasons SET status='paused',paused_at=1000")
        self.assertEqual(background.pending(w.path,1200),[])

    def test_error_does_not_kill_worker_loop(self):
        w=self.world();worker=self.coordinator(w)
        worker.stopping=MagicMock()
        worker.stopping.is_set.side_effect=[False,False,True]
        with patch.object(worker,'run_once',side_effect=[ValueError('fixture'),{'status':'ready'}]), \
             patch.object(worker,'record') as record:
            worker._run()
        self.assertEqual([call.args[0] for call in record.call_args_list],
                         ['background_started','background_error','background_stopped'])
        self.assertEqual([call.args[0] for call in worker.stopping.wait.call_args_list],[3,0.15])

    def test_admin_tail_escapes_records_and_filters_database(self):
        w=self.world();path=Path(w.tmp.name)/'background.jsonl'
        rows=[{'database':w.path.name,'event':'<script>alert(1)</script>','timestamp_utc':'fixture'},
              {'database':'other.db','event':'private-other-save'}]
        path.write_text('\n'.join(json.dumps(row) for row in rows)+'\nmalformed',encoding='utf-8')
        html=background.panel(w.path,path)
        self.assertIn('&lt;script&gt;',html)
        self.assertNotIn('<script>',html)
        self.assertNotIn('private-other-save',html)


class LaunchBackgroundTests(unittest.TestCase):
    def test_normal_launch_starts_and_stops_coordinator_after_binding(self):
        import serve_game
        gate=Lock();app=SimpleNamespace(game_database=Path('fixture.db'),gameplay_lock=gate,game_clock=lambda:1000)
        calls=[]
        server=MagicMock();worker=MagicMock()
        def bind(*args,**kwargs):calls.append('bind');return server
        worker.start.side_effect=lambda:calls.append('start')
        server.run.side_effect=lambda:calls.append('serve')
        worker.stop.side_effect=lambda:calls.append('stop')
        server.close.side_effect=lambda:calls.append('close')
        with patch('serve_game.create_app',return_value=app), \
             patch('waitress.create_server',side_effect=bind), \
             patch('game.background.Coordinator',return_value=worker):
            self.assertEqual(serve_game.main([]),0)
        self.assertEqual(calls,['bind','start','serve','stop','close'])

    def test_launch_switch_disables_coordinator(self):
        import serve_game
        app=SimpleNamespace(game_database=Path('fixture.db'))
        with patch('serve_game.create_app',return_value=app), \
             patch('waitress.create_server') as server, \
             patch('game.background.Coordinator') as worker:
            self.assertEqual(serve_game.main(['--no-background-catchup']),0)
        worker.assert_not_called();server.return_value.run.assert_called_once()

    def test_bind_failure_does_not_start_background_simulation(self):
        import serve_game
        with patch('serve_game.create_app'), \
             patch('waitress.create_server',side_effect=OSError('port occupied')), \
             patch('game.background.Coordinator') as worker:
            self.assertEqual(serve_game.main([]),1)
        worker.assert_not_called()

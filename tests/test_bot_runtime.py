"""Reproduce audit-write locks without running bots or a player server."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from game import bot_runtime
from run_bots import run_iteration,cleanup_session,main


class BotRuntimeTests(unittest.TestCase):
    def test_trace_lock_falls_back_without_recursive_database_write(self):
        with patch('game.bots.trace',side_effect=sqlite3.OperationalError('database is locked')) as write, \
             patch('game.bot_runtime.fallback') as fallback:
            self.assertFalse(bot_runtime.trace('fixture.db',4,'step_started',{'step':2}))
        write.assert_called_once()
        self.assertEqual(fallback.call_args.args[2],'step_started')
        self.assertTrue(fallback.call_args.args[3]['database_locked'])

    def test_record_lock_retains_decision_and_request_id_without_replay(self):
        decision=dict(route='/market',reason='Buy Food',form=dict(action='reserve_buy',resource='food',quantity=10))
        with patch('game.bots.record',side_effect=sqlite3.OperationalError('database is locked')) as write, \
             patch('game.bot_runtime.fallback') as fallback:
            self.assertFalse(bot_runtime.record('fixture.db',4,1000,decision,303,'request-id'))
        write.assert_called_once()
        payload=fallback.call_args.args[3]
        self.assertEqual(payload['decision'],decision)
        self.assertEqual(payload['request_id'],'request-id')
        self.assertIn('No action replay',payload['outcome'])

    def test_step_lock_and_error_handler_lock_do_not_stop_iteration(self):
        bot=dict(account_id=4,steps=2)
        with patch('run_bots.bots.claim',return_value=bot), \
             patch('run_bots.step',side_effect=sqlite3.OperationalError('database is locked')) as step, \
             patch('game.bots.trace',side_effect=sqlite3.OperationalError('database is locked')), \
             patch('game.bots.record',side_effect=sqlite3.OperationalError('database is locked')), \
             patch('game.bot_runtime.fallback') as fallback,patch('builtins.print'):
            self.assertTrue(run_iteration('fixture.db','http://127.0.0.1:8767'))
        step.assert_called_once();self.assertEqual(fallback.call_count,2)

    def test_session_cleanup_lock_does_not_override_action_result(self):
        with patch('run_bots.connect_database',side_effect=sqlite3.OperationalError('database is locked')), \
             patch('game.bot_runtime.fallback') as fallback:
            cleanup_session('fixture.db',4,'SECRET-SESSION-TOKEN')
        self.assertEqual(fallback.call_args.args[2],'session_cleanup_deferred')
        self.assertNotIn('SECRET-SESSION-TOKEN',str(fallback.call_args))

    def test_claim_lock_waits_and_loop_can_continue(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'fixture.db';path.touch()
            with patch('run_bots.bots.prepare'), \
                 patch('run_bots.run_iteration',side_effect=[sqlite3.OperationalError('database is locked'),KeyboardInterrupt]), \
                 patch('game.bot_runtime.fallback'),patch('run_bots.time.sleep') as wait,patch('builtins.print'):
                main(['--database',str(path)])
            wait.assert_called_once_with(3)

    def test_corruption_is_not_mislabelled_as_transient_lock(self):
        self.assertFalse(bot_runtime.locked(sqlite3.OperationalError('no such table: missing')))
        self.assertTrue(bot_runtime.locked(sqlite3.OperationalError('database table is locked')))

    def test_file_log_is_readable_filtered_and_html_escaped(self):
        with tempfile.TemporaryDirectory() as folder,patch('game.bot_runtime.LOG_PATH',Path(folder)/'fallback.jsonl'):
            bot_runtime.fallback('fixture.db',4,'test',{'message':'<script>unsafe</script>'})
            bot_runtime.fallback('other.db',5,'other',{})
            rows=[json.loads(line) for line in bot_runtime.LOG_PATH.read_text().splitlines()]
            self.assertEqual(rows[0]['account_id'],4);self.assertIn('timestamp_utc',rows[0])
            html=bot_runtime.fallback_panel('fixture.db')
            self.assertIn('&lt;script&gt;',html);self.assertNotIn('<script>',html)
            self.assertNotIn('other.db',html)

    def test_unwritable_fallback_does_not_raise_another_error(self):
        with patch('game.bot_runtime.RotatingFileHandler',side_effect=OSError('permission denied')), \
             patch('game.bot_runtime.LOG_PATH') as path,patch('builtins.print') as notice:
            bot_runtime.fallback('fixture.db',4,'failed',{})
        notice.assert_called_once()

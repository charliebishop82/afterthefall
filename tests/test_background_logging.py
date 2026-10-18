"""Reporting must retain its audit trail without holding the gameplay gate."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
import unittest
from unittest.mock import patch

from game.background import Coordinator


class BackgroundLoggingTests(unittest.TestCase):
    def worker(self):
        temp=TemporaryDirectory();self.addCleanup(temp.cleanup)
        worker=Coordinator(Path(temp.name)/'fixture.db',Lock(),clock=lambda:1200,
                           log_path=Path(temp.name)/'background.jsonl')
        self.addCleanup(worker.close_log)
        return worker

    def test_reporting_releases_gate_but_batch_keeps_it(self):
        worker=self.worker();events=[];lines=[]
        rows=[dict(account_id=1,settlement_id=2,behind=200,
                   simulation_seconds=200,skip_seconds=0)]
        result=dict(status='ready',processed_settlement_id=2,step_limits={'horizon':1})
        def batch(*args):
            self.assertTrue(worker.gate.locked())
            return result
        def record(event,**data):
            self.assertTrue(worker.gate.acquire(blocking=False))
            worker.gate.release();events.append((event,data))
        def output(*args,**kwargs):
            self.assertFalse(worker.gate.locked());lines.append(args[0])
        with patch('game.background.pending',return_value=rows), \
             patch('game.background.catchup.step',side_effect=batch), \
             patch.object(worker,'record',side_effect=record), \
             patch('game.background.time.monotonic',return_value=100), \
             patch('builtins.print',side_effect=output):
            self.assertIs(worker.run_once(),result)
        self.assertEqual([event for event,data in events],['background_batch','background_progress'])
        self.assertEqual(events[0][1]['processed_settlement_id'],2)
        self.assertEqual(events[1][1]['settlements'][0]['step_limits'],{'horizon':1})
        self.assertEqual(len(lines),2)

    def test_handler_is_reused_rotates_and_closes(self):
        worker=self.worker();worker.record('first')
        handler=worker._log_handler
        handler.maxBytes=1  # Force rotation without generating megabytes.
        worker.record('second',status='ready')
        self.assertIs(worker._log_handler,handler)
        self.assertEqual(json.loads(worker.log_path.read_text(encoding='utf-8'))['event'],'second')
        previous=worker.log_path.with_name(worker.log_path.name+'.1')
        self.assertEqual(json.loads(previous.read_text(encoding='utf-8'))['event'],'first')
        worker.close_log();worker.close_log()
        self.assertIsNone(handler.stream)
        self.assertIsNone(worker._log_handler)

    def test_worker_shutdown_closes_log_and_restart_can_reopen(self):
        worker=self.worker();worker.stopping.set();worker._run()
        self.assertIsNone(worker._log_handler)
        rows=[json.loads(line) for line in worker.log_path.read_text(encoding='utf-8').splitlines()]
        self.assertEqual([row['event'] for row in rows],['background_started','background_stopped'])
        worker.record('reopened')
        self.assertIsNotNone(worker._log_handler)

    def test_handler_creation_failure_does_not_discard_batch_result(self):
        worker=self.worker();worker.last_report=100
        rows=[dict(account_id=1,settlement_id=2)]
        result={'status':'ready'}
        with patch('game.background.pending',return_value=rows), \
             patch('game.background.catchup.step',return_value=result), \
             patch('game.background.time.monotonic',return_value=100), \
             patch('game.background.RotatingFileHandler',side_effect=OSError('fixture')), \
             patch('builtins.print') as output:
            self.assertIs(worker.run_once(),result)
        self.assertFalse(worker.gate.locked())
        output.assert_called_once_with('Background simulation log unavailable.',flush=True)

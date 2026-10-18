"""Bot reads and scheduling on minimal temporary tables; no game world or HTTP."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from database.create_database import connect_database
from game import bots
import run_bots


class BotPacingTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.path=Path(temp.name)/'bots.db'
        with closing(sqlite3.connect(self.path)) as c,c:
            c.executescript("""
                CREATE TABLE accounts(account_id INTEGER PRIMARY KEY,is_active INTEGER);
                CREATE TABLE settlements(settlement_id INTEGER PRIMARY KEY,account_id INTEGER);
                CREATE TABLE bot_controllers(account_id INTEGER PRIMARY KEY,state TEXT,seed INTEGER,
                    interval_seconds INTEGER,next_at INTEGER,lease_until INTEGER,steps INTEGER);
                INSERT INTO accounts VALUES(1,1);
                INSERT INTO settlements VALUES(10,1);
                INSERT INTO bot_controllers VALUES(1,'running',123,30,1000,0,0);
            """)
        self.bot=dict(account_id=1,seed=123,steps=0,interval_seconds=30)

    def test_claim_staggers_and_persists_next_decision_without_early_reclaim(self):
        claimed=bots.claim(self.path,1000)
        delay=claimed['decision_delay_seconds']
        self.assertGreaterEqual(delay,60);self.assertLessEqual(delay,120)
        self.assertEqual(claimed['scheduled_next_at'],1000+delay)
        with closing(connect_database(self.path)) as c,c:
            self.assertEqual(c.execute('SELECT next_at,lease_until FROM bot_controllers').fetchone(),(1000+delay,1120))
            c.execute('UPDATE bot_controllers SET lease_until=0,steps=steps+1')
        self.assertIsNone(bots.claim(self.path,999+delay))
        self.assertIsNotNone(bots.claim(self.path,1000+delay))

    def test_pacing_preserves_long_intervals_and_is_independent_of_policy_rng(self):
        import random
        before=random.getstate()
        slow=dict(self.bot,interval_seconds=300)
        delay=bots.decision_delay(slow)
        self.assertGreaterEqual(delay,300);self.assertLessEqual(delay,360)
        self.assertEqual(delay,bots.decision_delay(slow))
        delays={bots.decision_delay(dict(self.bot,account_id=i)) for i in range(1,10)}
        self.assertGreater(len(delays),1)
        self.assertEqual(random.getstate(),before)
        with self.assertRaises(ValueError):bots.claim(self.path,1000,min_interval=0)

    def test_idle_poll_does_not_begin_a_write_transaction(self):
        statements=[]
        with closing(connect_database(self.path)) as c,c:
            c.execute("UPDATE bot_controllers SET state='paused'")
        original=connect_database
        def connect(path):
            c=original(path);c.set_trace_callback(statements.append);return c
        with patch('game.bots.connect_database',side_effect=connect):
            self.assertIsNone(bots.claim(self.path,1000))
        self.assertFalse(any(sql.startswith('BEGIN') for sql in statements))

    def run_step(self,decision,status=200,identity=None):
        state=dict(settlement=dict(account_id=1,settlement_id=10),season=dict(season_id=2,map_seed=3))
        values=dict(account_id=1,settlement_id=10,season_id=2,map_seed=3,rates={})
        values.update(identity or {})
        responses=[(status,json.dumps(values).encode(),'refresh-id')]
        if decision.get('route'):responses.append((303,b'','action-id'))
        with patch('run_bots.time.time',return_value=1000), \
             patch('run_bots.accounts.new_session',return_value=('secret',{'csrf':'token'})), \
             patch('run_bots.cleanup_session') as cleanup, \
             patch('run_bots.read_state',return_value=state) as read, \
             patch('run_bots.choose',return_value=decision) as choose, \
             patch('run_bots.observations',return_value={'safe':True}), \
             patch('run_bots.bot_runtime.trace') as trace, \
             patch('run_bots.bot_runtime.record') as record, \
             patch('run_bots.request',side_effect=responses) as request:
            result=run_bots.step(self.path,'http://127.0.0.1:8767',self.bot)
        cleanup.assert_called_once()
        return result,read,request,trace,record,choose

    def test_wait_reads_full_state_once_and_keeps_observation_and_decision_logs(self):
        result,read,request,trace,record,choose=self.run_step(dict(route=None,reason='Wait',form={}))
        self.assertEqual(result,'Wait');self.assertEqual(read.call_count,1)
        self.assertEqual(request.call_count,1)
        self.assertEqual([call.args[2] for call in trace.call_args_list],['step_started','observed','decided','wait'])
        record.assert_called_once();choose.assert_called_once()

    def test_action_keeps_fresh_before_and_after_reads_and_all_audit_phases(self):
        _,read,request,trace,record,_=self.run_step(dict(route='/buildings',reason='Build',form={'action':'build'}))
        self.assertEqual(read.call_count,2);self.assertEqual(request.call_count,2)
        self.assertEqual([call.args[2] for call in trace.call_args_list],['step_started','observed','decided','action_started','action_completed'])
        self.assertEqual(record.call_args.args[4:6],(303,'action-id'))

    def test_rejected_refresh_never_loads_full_state_or_chooses_an_action(self):
        result,read,request,trace,record,choose=self.run_step(dict(route=None,reason='Wait',form={}),status=403)
        self.assertEqual(result,'Refresh rejected');read.assert_not_called();choose.assert_not_called()
        self.assertEqual(request.call_count,1)
        self.assertEqual(trace.call_args.args[2],'refresh_rejected')

    def test_wrong_server_identity_never_submits_an_action(self):
        result,read,request,trace,record,choose=self.run_step(dict(route='/buildings',reason='Build',form={}),identity={'settlement_id':999})
        self.assertEqual(result,'Controller error: ValueError');choose.assert_not_called()
        self.assertEqual(request.call_count,1);self.assertEqual(trace.call_args.args[2],'controller_error')

    def test_runner_waits_between_turns_and_idle_checks(self):
        with patch('run_bots.bots.prepare'), \
             patch('run_bots.run_iteration',side_effect=[True,False,KeyboardInterrupt]) as iteration, \
             patch('run_bots.time.sleep') as sleep,patch('builtins.print'):
            run_bots.main(['--database',str(self.path),'--min-interval','90','--jitter','30','--action-gap','7'])
        self.assertEqual([call.args[0] for call in sleep.call_args_list],[7,2])
        self.assertEqual(iteration.call_args.kwargs,dict(min_interval=90,jitter=30))

    def test_unenrolled_bot_waits_without_state_load_or_session_creation(self):
        with closing(connect_database(self.path)) as c,c:c.execute('DELETE FROM settlements')
        with patch('run_bots.accounts.new_session') as session, \
             patch('run_bots.read_state') as read, \
             patch('run_bots.bot_runtime.trace') as trace, \
             patch('run_bots.bot_runtime.record') as record:
            run_bots.step(self.path,'http://127.0.0.1:8767',self.bot)
        session.assert_not_called();read.assert_not_called();record.assert_called_once()
        self.assertEqual(trace.call_args.args[2],'waiting_for_settlement')

    def test_paused_controller_never_submits_chosen_action(self):
        with closing(connect_database(self.path)) as c,c:
            c.execute("UPDATE bot_controllers SET state='paused'")
        result,read,request,trace,record,choose=self.run_step(dict(route='/buildings',reason='Build',form={}))
        self.assertEqual(result,'Controller paused before action.')
        self.assertEqual(request.call_count,1);self.assertEqual(read.call_count,1)
        self.assertEqual(trace.call_args.args[2],'wait')

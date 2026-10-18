"""Offline allowance is persistent; local progress pauses, shared clocks do not."""
from contextlib import closing
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from database.create_database import connect_database
from game import offline, expansion, banking, catchup
from game.settlement import account_scope, read_state
from game.simulation import advance_settlement
from tests.fixtures import SupportWorld, fixed_map_seed


class OfflineCapTests(unittest.TestCase):
    def world(self):
        with fixed_map_seed():w=SupportWorld(self)
        w.change('enable_consequences')
        return w

    def test_default_is_48_hours_and_other_accounts_cannot_renew_my_window(self):
        self.assertEqual(offline.settings()['max_hours'],48)
        w=self.world()
        with closing(connect_database(w.path)) as c,account_scope(w.a):
            before=offline.cutoff(c,w.state())
        offline.touch(w.path,w.b,2000)
        with closing(connect_database(w.path)) as c,account_scope(w.a):
            self.assertEqual(offline.cutoff(c,w.state()),before)
        offline.touch(w.path,w.a,2000)
        with closing(connect_database(w.path)) as c,account_scope(w.a):
            self.assertEqual(offline.cutoff(c,w.state()),2000+48*3600)

    def test_only_allowed_hours_are_simulated_and_repeated_reads_do_not_grant_more(self):
        w=self.world();copy=Path(w.tmp.name)/'uncapped.db'
        with closing(connect_database(w.path)) as source,closing(sqlite3.connect(copy)) as target:
            source.backup(target)
        # Use a shorter configurable limit to exercise the same boundary without
        # making this regression test replay two days of detailed simulation.
        with patch('game.offline.settings',return_value={'enabled':False,'max_hours':1}),account_scope(w.a):
            expected=advance_settlement(copy,4600)
        with patch('game.offline.settings',return_value={'enabled':True,'max_hours':1}),account_scope(w.a):
            actual=advance_settlement(w.path,11800)
            again=advance_settlement(w.path,15400)
        self.assertEqual(actual['settlement']['simulation_processed_at'],11800)
        self.assertEqual(again['settlement']['simulation_processed_at'],15400)
        for resource in ('food','water','scrap','metal','electronics','credits'):
            self.assertAlmostEqual(actual['resources'][resource],expected['resources'][resource],places=7)
            self.assertEqual(again['resources'][resource],actual['resources'][resource])
        for a,b in zip(actual['citizens'],expected['citizens']):
            for key in ('xp','level','current_hp','morale'):
                self.assertAlmostEqual(a[key],b[key],places=7,msg=key)
        self.assertEqual(w.sql('SELECT last_active_at FROM settlement_activity WHERE settlement_id=?',(w.sa,)),[(1000,)])
        self.assertGreater(w.sql("SELECT count(*) FROM game_events WHERE event_type='offline_time_capped'")[0][0],0)

    def test_returning_player_gets_new_allowance_after_completed_catchup(self):
        w=self.world()
        with patch('game.offline.settings',return_value={'enabled':True,'max_hours':1}),account_scope(w.a):
            first=advance_settlement(w.path,11800)
            offline.touch(w.path,w.a,11800)
            second=advance_settlement(w.path,15400)
        self.assertLess(second['resources']['food'],first['resources']['food'])
        self.assertEqual(second['settlement']['simulation_processed_at'],15400)

    def test_batch_after_cutoff_skips_excess_once_without_renewing_activity(self):
        w=self.world()
        w.sql('UPDATE settlements SET simulation_processed_at=4600 WHERE settlement_id=?',(w.sa,))
        before=w.state()['resources'].copy()
        with patch('game.offline.settings',return_value={'enabled':True,'max_hours':1}):
            result=catchup.step(w.path,w.a,11800)
        self.assertEqual(result['status'],'ready')
        self.assertEqual(w.state()['settlement']['simulation_processed_at'],11800)
        self.assertEqual(w.state()['resources'],before)
        self.assertEqual(w.sql('SELECT last_active_at FROM settlement_activity WHERE settlement_id=?',(w.sa,)),[(1000,)])

    def test_skipped_time_keeps_protection_and_bank_deadlines_real(self):
        w=self.world()
        with account_scope(w.a):expansion.transact(w.path,'enable',1000)
        with closing(connect_database(w.path)) as c,c,account_scope(w.a):
            c.row_factory=sqlite3.Row
            state=read_state(c)
            loan=banking.borrow(c,state,100,1000)
            deadline=state['settlement']['protection_until']
            end=state['season']['ends_at']
            offline.skip(c,read_state(c),3*86400+1000)
            current=read_state(c)
            self.assertEqual(current['settlement']['protection_until'],deadline)
            self.assertEqual(current['season']['ends_at'],end)
            row=c.execute('SELECT outstanding_balance,interest_processed_at FROM bank_loans WHERE loan_id=?',(loan,)).fetchone()
            self.assertGreater(row['outstanding_balance'],100)
            self.assertEqual(row['interest_processed_at'],3*86400)

    def test_skipping_preserves_pending_local_grace_and_admin_pause_preserves_allowance(self):
        w=self.world()
        with closing(connect_database(w.path)) as c,c,account_scope(w.a):
            c.row_factory=sqlite3.Row
            state=read_state(c);cut=offline.cutoff(c,state)
            recovery_anchor=state['recovery_clock']['anchor']
            offline.skip(c,state,4600)
            current=read_state(c)
            self.assertEqual(current['recovery_clock']['anchor'],recovery_anchor+3600)
            self.assertEqual(offline.cutoff(c,current),cut)
            from game.recovery import shift_clock
            shift_clock(c,current,600,5200)
            self.assertEqual(offline.cutoff(c,read_state(c)),cut+600)

    def test_activity_table_migration_is_idempotent_and_does_not_change_progress(self):
        w=self.world();before=w.state()
        with closing(connect_database(w.path)) as c,c:
            offline.prepare(c);offline.prepare(c)
        self.assertEqual(w.state(),before)
        self.assertEqual(w.sql('SELECT count(*) FROM settlement_activity')[0][0],2)

    def test_missing_or_legacy_scope_has_no_cap(self):
        w=self.world()
        with closing(connect_database(w.path)) as c:
            self.assertIsNone(offline.cutoff(c,w.state()))
            state=w.state();state['season']['config_version']='prototype_v10'
            with account_scope(w.a):self.assertIsNone(offline.cutoff(c,state))

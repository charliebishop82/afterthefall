"""Parallel orchestration report checks; no subprocesses or game saves needed."""
import json
from pathlib import Path
import tempfile
import unittest

from run_tests_parallel import modules, read_result, summary, final_report, ui_result, schedule, select_suite


class ParallelRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_quick_selection_is_explicit_and_full_keeps_new_modules(self):
        tests=self.root/'tests';tests.mkdir()
        (tests/'quick-suite.json').write_text('["one.py"]',encoding='utf-8')
        discovered=['one.py','new.py','ui.cjs']
        self.assertEqual(select_suite(discovered,self.root,'full'),discovered)
        self.assertEqual(select_suite(discovered,self.root,'quick'),['one.py','ui.cjs'])

    def test_bad_quick_manifest_fails_instead_of_dropping_tests_silently(self):
        tests=self.root/'tests';tests.mkdir()
        path=tests/'quick-suite.json'
        for body in ('[]','{}','["one.py","one.py"]','["missing.py"]','[1]'):
            path.write_text(body,encoding='utf-8')
            with self.assertRaises(ValueError):select_suite(['one.py'],self.root,'quick')

    def test_quick_report_cannot_be_mistaken_for_a_full_pass(self):
        data=summary([dict(module='one',successful=True,tests_run=1)],['one'],1,False,suite='quick',discovered=['one','two'])
        self.assertEqual(data['modules_excluded'],['two'])
        self.assertTrue(data['successful'])
        self.assertIn('not a full regression result',final_report(data))

    def history(self,name,rows):
        folder=self.root/name;folder.mkdir()
        (folder/'summary.json').write_text(json.dumps({'modules':rows}),encoding='utf-8')

    def test_scheduling_runs_long_modules_first_without_dropping_unknown_modules(self):
        self.history('parallel-20261017',[dict(module='fast.py',elapsed_seconds=2),dict(module='slow.py',elapsed_seconds=30)])
        ordered,history=schedule(['fast.py','new.py','slow.py'],self.root)
        self.assertEqual(ordered,['slow.py','new.py','fast.py'])
        self.assertEqual(history,{'fast.py':2.0,'slow.py':30.0})

    def test_scheduling_prefers_recent_timings_and_can_restore_alphabetical_order(self):
        self.history('parallel-20261016',[dict(module='one.py',elapsed_seconds=90)])
        self.history('parallel-20261017',[dict(module='one.py',elapsed_seconds=1),dict(module='two.py',elapsed_seconds=5)])
        planned=['one.py','two.py']
        self.assertEqual(schedule(planned,self.root)[0],['two.py','one.py'])
        self.assertEqual(schedule(planned,self.root,order='alphabetical'),(planned,{}))

    def test_scheduling_ignores_bad_history_and_uses_alphabetical_fallback(self):
        self.history('parallel-20261017',[None,dict(module='one.py',elapsed_seconds=-1),dict(module='two.py',elapsed_seconds=True),dict(module='three.py',elapsed_seconds=float('nan')),dict(module='foreign.py',elapsed_seconds=99)])
        ordered,history=schedule(['two.py','one.py','three.py'],self.root)
        self.assertEqual(ordered,['one.py','three.py','two.py'])
        self.assertEqual(history,{})
        (self.root/'parallel-20261017/summary.json').write_text('broken',encoding='utf-8')
        self.assertEqual(schedule(['b','a'],self.root)[0],['a','b'])

    def test_scheduling_can_use_finished_workers_from_an_interrupted_run(self):
        folder=self.root/'parallel-20261017';folder.mkdir()
        (folder/'001-one.json').write_text(json.dumps(dict(module='one.py',elapsed_seconds=12)),encoding='utf-8')
        (folder/'plan.json').write_text('["one.py"]',encoding='utf-8')
        self.assertEqual(schedule(['one.py'],self.root),(['one.py'],{'one.py':12.0}))

    def test_final_report_includes_slow_tests_without_hiding_failures(self):
        rows=[dict(module='one',successful=False,tests_run=1,elapsed_seconds=8,tests=[dict(test='one.C.case',seconds=7,outcome='failed')])]
        output=final_report(summary(rows,['one'],8,False))
        self.assertIn('OVERALL: INCOMPLETE / FAIL',output)
        self.assertIn('SLOWEST MODULES',output)
        self.assertIn('7.000s  one.C.case [failed]',output)

    def test_discovery_keeps_importable_nested_modules(self):
        tests = self.root/'tests'; tests.mkdir()
        (tests/'test_top.py').touch()
        nested = tests/'nested'; nested.mkdir()
        (nested/'__init__.py').touch(); (nested/'test_child.py').touch()
        ignored = tests/'not_a_package'; ignored.mkdir()
        (ignored/'test_hidden.py').touch(); (tests/'helper.py').touch()
        self.assertEqual(modules(self.root), ['nested/test_child.py', 'test_top.py'])

    def test_process_failure_overrides_successful_report(self):
        path = self.root/'report.json'
        path.write_text(json.dumps(dict(successful=True, tests_run=3)), encoding='utf-8')
        self.assertFalse(read_result(path, 1, 'test_one.py')['successful'])
        self.assertTrue(read_result(path, 0, 'test_one.py')['successful'])

    def test_missing_invalid_or_empty_reports_fail(self):
        path = self.root/'report.json'
        self.assertFalse(read_result(path, 0, 'test_one.py')['successful'])
        for body in ('broken', '[]', '{"tests_run": "3"}', '{"tests_run": 0, "successful": true}'):
            path.write_text(body, encoding='utf-8')
            self.assertFalse(read_result(path, 0, 'test_one.py')['successful'])

    def test_complete_summary_counts_failures_and_skips(self):
        rows = [dict(module='one', successful=True, tests_run=3, skipped=1),
                dict(module='two', successful=False, tests_run=4, failures=1, errors=2)]
        data = summary(rows, ['one', 'two'], 12, False)
        self.assertFalse(data['successful'])
        self.assertEqual((data['tests_run'], data['failures'], data['errors'], data['skipped']), (7, 1, 2, 1))
        self.assertEqual(data['unfinished'], [])

    def test_interrupted_or_partial_runs_cannot_pass(self):
        rows = [dict(module='one', successful=True, tests_run=1)]
        self.assertTrue(summary(rows, ['one'], 1, False)['successful'])
        self.assertFalse(summary(rows, ['one'], 1, True)['successful'])
        partial = summary(rows, ['one', 'two'], 1, False)
        self.assertFalse(partial['successful'])
        self.assertEqual(partial['unfinished'], ['two'])
        self.assertFalse(summary([], [], 0, False)['successful'])

    def test_final_report_lists_every_module_and_failure_details(self):
        rows=[dict(module='good',successful=True,tests_run=2),
              dict(module='bad',successful=False,tests_run=1,exit_code=1,
                   failure_details=[dict(test='test_bad_case',outcome='failed',traceback='AssertionError: example')])]
        output=final_report(summary(rows,['good','bad','waiting'],2,False))
        for expected in ('PASS  good','FAIL  bad','INCOMPLETE  waiting','test_bad_case','AssertionError: example'):
            self.assertIn(expected,output)

    def test_ui_tap_summary_counts_failures_and_rejects_empty_output(self):
        log=self.root/'ui.log'
        log.write_text('# tests 3\n# fail 1\n# skipped 1\n# cancelled 0\n',encoding='utf-8')
        result=ui_result(log,1,'test_ui.cjs')
        self.assertFalse(result['successful'])
        self.assertEqual((result['tests_run'],result['failures'],result['skipped']),(3,1,1))
        log.write_text('# tests 0\n# fail 0\n',encoding='utf-8')
        self.assertFalse(ui_result(log,0,'test_ui.cjs')['successful'])

    def test_discovery_includes_new_modules_on_the_next_run(self):
        tests=self.root/'tests';tests.mkdir()
        (tests/'test_old.py').touch()
        self.assertEqual(modules(self.root),['test_old.py'])
        (tests/'test_new.py').touch()
        self.assertEqual(modules(self.root),['test_new.py','test_old.py'])

"""Parallel orchestration report checks; no subprocesses or game saves needed."""
import json
from pathlib import Path
import tempfile
import unittest

from run_tests_parallel import modules, read_result, summary, final_report, ui_result


class ParallelRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

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

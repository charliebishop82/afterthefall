"""Timing observes real unittest outcomes without changing pass/fail behavior."""
import io
import unittest

from run_tests import TimedResult, report


class RunnerTests(unittest.TestCase):
    def execute(self, case):
        ticks=[0]
        result=TimedResult(unittest.runner._WritelnDecorator(io.StringIO()),True,0,clock=lambda:ticks[0])
        case.ticks=ticks
        case.run(result)
        return result

    def test_timing_includes_setup_test_teardown_and_cleanup(self):
        class Case(unittest.TestCase):
            def setUp(self):
                self.ticks[0]+=1
                self.addCleanup(self.cleanup)
            def cleanup(self): self.ticks[0]+=4
            def runTest(self): self.ticks[0]+=2
            def tearDown(self): self.ticks[0]+=3
        result=self.execute(Case())
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(result.timings[0]['seconds'],10)
        self.assertEqual(result.timings[0]['outcome'],'passed')

    def test_failure_and_error_keep_unsuccessful_results(self):
        class Failure(unittest.TestCase):
            def runTest(self): self.fail('intentional runner fixture')
        class Error(unittest.TestCase):
            def runTest(self): raise ValueError('intentional runner fixture')
        for case,status in ((Failure(),'failed'),(Error(),'error')):
            with self.subTest(status=status):
                result=self.execute(case)
                self.assertFalse(result.wasSuccessful())
                self.assertEqual(result.timings[0]['outcome'],status)

    def test_failed_subtest_is_not_reported_as_passed(self):
        class Case(unittest.TestCase):
            def runTest(self):
                with self.subTest(value=1): self.assertEqual(1,2)
        result=self.execute(Case())
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(result.timings[0]['outcome'],'failed')
        self.assertEqual(len(result.timings),1)

    def test_skipped_and_expected_failure_outcomes(self):
        class Skip(unittest.TestCase):
            @unittest.skip('intentional runner fixture')
            def runTest(self): pass
        class Expected(unittest.TestCase):
            @unittest.expectedFailure
            def runTest(self): self.fail('intentional runner fixture')
        for case,status in ((Skip(),'skipped'),(Expected(),'expected failure')):
            with self.subTest(status=status):
                result=self.execute(case)
                self.assertTrue(result.wasSuccessful())
                self.assertEqual(result.timings[0]['outcome'],status)

    def test_unexpected_success_still_fails(self):
        class Case(unittest.TestCase):
            @unittest.expectedFailure
            def runTest(self): pass
        result=self.execute(Case())
        self.assertFalse(result.wasSuccessful())
        self.assertEqual(result.timings[0]['outcome'],'unexpected success')

    def test_report_sorts_tests_and_totals_modules(self):
        result=TimedResult(unittest.runner._WritelnDecorator(io.StringIO()),True,0)
        result.testsRun=3
        result.timings=[{'test':'one.A.test_x','seconds':1,'outcome':'passed'},
                        {'test':'two.B.test_y','seconds':5,'outcome':'passed'},
                        {'test':'one.A.test_z','seconds':2,'outcome':'passed'}]
        data=report(result,9)
        self.assertEqual([r['seconds'] for r in data['tests']],[5,2,1])
        self.assertEqual(data['modules']['one'],{'tests':2,'seconds':3})
        self.assertEqual(data['tests_run'],3)
        self.assertTrue(data['successful'])

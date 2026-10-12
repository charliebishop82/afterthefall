"""Run the full regression suite from any working directory."""

import argparse
import json
from pathlib import Path
import sys
import time
import unittest


class TimedResult(unittest.TextTestResult):
    """Time each complete test, including setup, teardown and registered cleanup."""
    def __init__(self, stream, descriptions, verbosity, *, clock=time.perf_counter):
        super().__init__(stream, descriptions, verbosity)
        self.clock = clock
        self.timings = []

    def startTest(self, test):
        self.started = self.clock()
        self.outcome = 'incomplete'
        super().startTest(test)

    def stopTest(self, test):
        self.timings.append({'test':test.id(), 'seconds':max(0, self.clock()-self.started), 'outcome':self.outcome})
        super().stopTest(test)

    def addSuccess(self, test):
        self.outcome = 'passed'
        super().addSuccess(test)

    def addFailure(self, test, error):
        self.outcome = 'failed'
        super().addFailure(test, error)

    def addError(self, test, error):
        self.outcome = 'error'
        super().addError(test, error)

    def addSkip(self, test, reason):
        self.outcome = 'skipped'
        super().addSkip(test, reason)

    def addExpectedFailure(self, test, error):
        self.outcome = 'expected failure'
        super().addExpectedFailure(test, error)

    def addUnexpectedSuccess(self, test):
        self.outcome = 'unexpected success'
        super().addUnexpectedSuccess(test)

    def addSubTest(self, test, subtest, error):
        if error is not None:
            self.outcome = 'failed' if issubclass(error[0],test.failureException) else 'error'
        super().addSubTest(test, subtest, error)


def report(result, elapsed):
    ordered = sorted(result.timings, key=lambda row:row['seconds'], reverse=True)
    modules = {}
    for row in ordered:
        module = row['test'].rsplit('.',2)[0]
        totals = modules.setdefault(module, {'tests':0, 'seconds':0})
        totals['tests'] += 1
        totals['seconds'] += row['seconds']
    return {'tests_run':result.testsRun, 'successful':result.wasSuccessful(),
            'elapsed_seconds':elapsed, 'tests':ordered, 'modules':modules}


def main(argv=None):
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timings',type=Path,default=root/'test-timings.json',help='Timing report path (default: project/test-timings.json)')
    parser.add_argument('--slowest',type=int,default=10,help='Number of slowest tests to print')
    args = parser.parse_args(argv)
    if args.slowest < 0: parser.error('--slowest must be nonnegative')
    sys.path.insert(0, str(root))
    suite = unittest.defaultTestLoader.discover(str(root / "tests"))
    if suite.countTestCases() == 0:
        print("ERROR: No tests were discovered.", file=sys.stderr)
        return 1
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2, resultclass=TimedResult).run(suite)
    timing = report(result, time.perf_counter()-started)
    try:
        args.timings.write_text(json.dumps(timing,indent=2)+'\n',encoding='utf-8')
    except OSError as error:
        print(f'ERROR: Could not write timing report: {error}',file=sys.stderr)
        return 1
    print(f'\nTiming report: {args.timings.resolve()}')
    if args.slowest:
        print('Slowest tests (including setup and cleanup):')
        for row in timing['tests'][:args.slowest]:
            print(f"  {row['seconds']:8.3f}s  {row['test']} [{row['outcome']}]")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

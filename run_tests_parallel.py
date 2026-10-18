"""Run Python regression modules in separate processes, with completion progress."""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import subprocess
import re
import shutil
import sys
import time
import unittest
from statistics import median

ROOT = Path(__file__).resolve().parent


def select_suite(discovered, root, suite):
    """Quick is an explicit smoke selection; full discovery remains the default."""
    if suite=='full':return list(discovered)
    if suite!='quick':raise ValueError('Unknown test suite.')
    manifest=json.loads((Path(root)/'tests/quick-suite.json').read_text(encoding='utf-8'))
    if (not isinstance(manifest,list) or not manifest or any(not isinstance(m,str) for m in manifest)
            or len(set(manifest))!=len(manifest)):
        raise ValueError('Quick-suite manifest must contain unique module names.')
    missing=set(manifest)-set(discovered)
    if missing:raise ValueError('Quick-suite modules are missing from discovery: '+', '.join(sorted(missing)))
    return [m for m in discovered if m in manifest or m.endswith('.cjs')]


def schedule(planned, output, order='slow-first'):
    """Use bounded saved history as a hint, never as a test selection filter."""
    if order=='alphabetical':return sorted(planned),{}
    durations={}
    folders=sorted((p for p in Path(output).glob('parallel-*') if p.is_dir()),reverse=True)[:5]
    for folder in folders:
        summary_path=folder/'summary.json'
        paths=[summary_path] if summary_path.is_file() else sorted(folder.glob('*.json'))
        for path in paths:
            if path.name in ('plan.json','schedule.json'):continue
            try:
                saved=json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(saved,dict):continue
                rows=saved.get('modules',[]) if path==summary_path else [saved]
                if not isinstance(rows,list):continue
                for row in rows:
                    if not isinstance(row,dict):continue
                    name=row.get('module');seconds=row.get('elapsed_seconds')
                    if (isinstance(name,str) and name in planned and name not in durations
                            and type(seconds) in (int,float) and math.isfinite(seconds) and seconds>0):
                        durations[name]=float(seconds)
            except (OSError,ValueError):continue
    neutral=median(durations.values()) if durations else 1.0
    return sorted(planned,key=lambda name:(-durations.get(name,neutral),name)),durations


def modules(root):
    """Mirror unittest discovery, including only importable nested directories."""
    tests = root / 'tests'
    found = []
    for path in tests.rglob('test*.py'):
        parent = path.parent
        while parent != tests and (parent / '__init__.py').is_file():
            parent = parent.parent
        if parent == tests:
            found.append(path.relative_to(tests).as_posix())
    return sorted(found)


def worker(relative, destination):
    from run_tests import TimedResult, report
    tests = ROOT / 'tests'
    target = (tests / relative).resolve()
    if not target.is_relative_to(tests.resolve()) or not target.is_file():
        raise ValueError('Worker target must be a test file within tests/.')
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(
        str(target.parent), pattern=target.name, top_level_dir=str(tests))
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2, resultclass=TimedResult).run(suite)
    data = report(result, time.perf_counter() - started)
    data.update(module=relative, failures=len(result.failures), errors=len(result.errors),
                skipped=len(result.skipped), expected_failures=len(result.expectedFailures),
                unexpected_successes=len(result.unexpectedSuccesses))
    data['failure_details'] = [dict(test=test.id(),outcome=outcome,traceback=detail)
        for outcome,entries in [('failed',result.failures),('error',result.errors)]
        for test,detail in entries]
    data['failure_details'] += [dict(test=test.id(),outcome='unexpected success',traceback='')
                               for test in result.unexpectedSuccesses]
    data['successful'] = result.wasSuccessful() and result.testsRun > 0
    if not result.testsRun:
        print('ERROR: This module discovered no tests.', file=sys.stderr)
    destination.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    return 0 if data['successful'] else 1


def read_result(path, code, module):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or not isinstance(data.get('tests_run'), int):
            raise ValueError('Invalid worker report')
        data['successful'] = code == 0 and data.get('successful') is True and data['tests_run'] > 0
    except (OSError, ValueError):
        data = dict(module=module, successful=False, tests_run=0,
                    report_error='Worker ended without a valid report; inspect its log.')
    data['exit_code'] = code
    return data


def summary(results, planned, elapsed, interrupted, *, suite='full', discovered=None):
    return dict(successful=not interrupted and len(results) == len(planned) and
                bool(planned) and all(r['successful'] for r in results),
                interrupted=interrupted, elapsed_seconds=elapsed,suite=suite,
                modules_excluded=[m for m in (discovered or planned) if m not in set(planned)],
                modules_planned=len(planned), modules_completed=len(results),
                tests_run=sum(r['tests_run'] for r in results),
                failures=sum(r.get('failures', 0) for r in results),
                errors=sum(r.get('errors', 0) for r in results),
                skipped=sum(r.get('skipped', 0) for r in results),
                unfinished=[m for m in planned if m not in {r['module'] for r in results}],
                modules=results)


def ui_result(log, code, module):
    output=log.read_text(encoding='utf-8',errors='replace')
    def count(label):
        match=re.search(r'^# '+label+r' (\d+)\s*$',output,re.M)
        return int(match[1]) if match else 0
    total=count('tests')
    return dict(module=module,successful=code==0 and total>0,tests_run=total,
                failures=count('fail'),errors=count('cancelled'),skipped=count('skipped'),
                exit_code=code,tests=[],failure_details=[])


def final_report(data):
    lines=['OVERALL: '+('PASS' if data['successful'] else 'INCOMPLETE / FAIL'),
           f"{data['tests_run']} tests; {data['modules_completed']}/{data['modules_planned']} modules; "
           f"{data['failures']} failures; {data['errors']} errors; {data['skipped']} skipped",
           '', 'MODULE RESULTS']
    if data.get('suite')=='quick':
        lines.insert(0,'QUICK SUITE ONLY — this is not a full regression result.')
        lines.insert(1,f"{len(data.get('modules_excluded',[]))} modules intentionally outside the quick selection; none counted as passed.")
    for row in sorted(data['modules'],key=lambda r:r['module']):
        lines.append(f"{'PASS' if row['successful'] else 'FAIL'}  {row['module']} — "
                     f"{row['tests_run']} tests, {row.get('elapsed_seconds',0):.1f}s")
    lines += ['INCOMPLETE  '+name for name in data['unfinished']]
    failed=[row for row in data['modules'] if not row['successful']]
    if failed: lines += ['', 'FAILURE DETAILS']
    for row in failed:
        lines += ['',row['module'],'Exit code: '+str(row.get('exit_code','unknown')),
                  'Full output: '+row.get('log','unavailable')]
        details=row.get('failure_details',[])
        for detail in details:
            lines += [detail['outcome'].upper()+': '+detail['test'],detail['traceback']]
        if row.get('report_error'): lines.append(row['report_error'])
        if not details and row.get('log'):
            try: lines.append(Path(row['log']).read_text(encoding='utf-8',errors='replace')[-12000:])
            except OSError: lines.append('Log unavailable.')
    if data['modules']:
        lines+=['','SLOWEST MODULES (wall time)']
        for row in sorted(data['modules'],key=lambda r:r.get('elapsed_seconds',0),reverse=True)[:10]:
            lines.append(f"{row.get('elapsed_seconds',0):.1f}s  {row['module']}")
        timings=[test for row in data['modules'] for test in (row.get('tests') or []) if isinstance(test,dict) and isinstance(test.get('seconds'),(int,float))]
        if timings:
            lines+=['','SLOWEST PYTHON TESTS (including setup and cleanup)']
            for test in sorted(timings,key=lambda t:t['seconds'],reverse=True)[:10]:
                lines.append(f"{test['seconds']:.3f}s  {test.get('test','unknown')} [{test.get('outcome','unknown')}]")
    return '\n'.join(lines)+'\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=int, default=2, help='Concurrent module processes (default: 2)')
    parser.add_argument('--output', type=Path, default=ROOT/'test-results', help='Parent folder for a new run directory')
    parser.add_argument('--include-ui',action='store_true',help='Also discover test*.cjs files using installed Node.js')
    parser.add_argument('--suite',choices=('full','quick'),default='full',help='Full regression (default) or curated everyday smoke suite')
    parser.add_argument('--order',choices=('slow-first','alphabetical'),default='slow-first',help='Module scheduling order (default: slow-first using saved durations)')
    parser.add_argument('--worker', help=argparse.SUPPRESS)
    parser.add_argument('--worker-report', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        if not args.worker_report: parser.error('Worker requires a report path.')
        return worker(args.worker, args.worker_report)
    if args.workers < 1: parser.error('--workers must be at least 1')
    planned = modules(ROOT)
    node = None
    if args.include_ui:
        node=shutil.which('node')
        if not node: parser.error('--include-ui requires Node.js; omit it for Python tests only.')
        planned += sorted(p.relative_to(ROOT/'tests').as_posix() for p in (ROOT/'tests').rglob('test*.cjs'))
    if not planned:
        print('ERROR: No test modules were found.', file=sys.stderr)
        return 1
    discovered=list(planned)
    try:planned=select_suite(discovered,ROOT,args.suite)
    except (OSError,ValueError) as error:parser.error(str(error))
    planned,history=schedule(planned,args.output,order=args.order)
    folder = args.output.resolve()/datetime.now(timezone.utc).strftime('parallel-%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True)
    print(f'{len(planned)} modules; up to {args.workers} workers. Python: {sys.executable}', flush=True)
    print(('QUICK SUITE ONLY — not a full regression result.' if args.suite=='quick' else 'FULL REGRESSION SUITE'),flush=True)
    print(f'Scheduling: {args.order}; {len(history)} saved module durations; {len(planned)}/{len(discovered)} discovered modules selected.',flush=True)
    print(f'Per-module logs and reports: {folder}', flush=True)
    (folder/'plan.json').write_text(json.dumps(planned, indent=2)+'\n', encoding='utf-8')
    (folder/'schedule.json').write_text(json.dumps(dict(suite=args.suite,order=args.order,historical_seconds=history,discovered=discovered),indent=2)+'\n',encoding='utf-8')
    started = time.perf_counter(); next_index = 0; running = []; results = []; interrupted = False
    last_update = started
    try:
        while next_index < len(planned) or running:
            while next_index < len(planned) and len(running) < args.workers:
                module = planned[next_index]; next_index += 1
                # Numbered filenames avoid clashes between nested modules with the same name.
                prefix = f'{next_index:03d}-'+module.replace('/', '__').removesuffix('.py')
                log = folder/(prefix+'.log'); report_path = folder/(prefix+'.json')
                stream = log.open('w', encoding='utf-8')
                try:
                    command=([node,'--test','--test-reporter=tap',str(ROOT/'tests'/module)] if module.endswith('.cjs') else
                             [sys.executable,'-u','-X','utf8',str(Path(__file__).resolve()),
                              '--worker',module,'--worker-report',str(report_path)])
                    process = subprocess.Popen(command,
                        cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
                except BaseException:
                    stream.close(); raise
                running.append((process, stream, module, log, report_path, time.perf_counter()))
                print(f'START {module}', flush=True)
            for item in running[:]:
                process, stream, module, log, report_path, module_started = item
                code = process.poll()
                if code is None: continue
                stream.close(); running.remove(item)
                result = ui_result(log,code,module) if module.endswith('.cjs') else read_result(report_path,code,module)
                result['elapsed_seconds']=time.perf_counter()-module_started
                if module.endswith('.cjs'): report_path.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
                result['log'] = str(log); result['module'] = module; results.append(result)
                status = 'PASS' if result['successful'] else 'FAIL'
                print(f'[{len(results)}/{len(planned)} modules] {status} {module}: '
                      f'{result["tests_run"]} tests, {result.get("elapsed_seconds", 0):.1f}s; '
                      f'{sum(r["tests_run"] for r in results)} tests finished; '
                      f'{time.perf_counter()-started:.1f}s elapsed', flush=True)
                if not result['successful']:
                    print(f'  Details: {log}', flush=True)
                    print(log.read_text(encoding='utf-8', errors='replace')[-12000:], flush=True)
            if time.perf_counter() - last_update >= 15:
                print(f'Progress: {len(results)}/{len(planned)} modules complete; '
                      f'{time.perf_counter()-started:.1f}s elapsed. Running: '
                      + ', '.join(item[2] for item in running), flush=True)
                last_update = time.perf_counter()
            time.sleep(.2)
    except KeyboardInterrupt:
        interrupted = True
        print('\nInterrupted; stopping test workers. Partial report will be saved.', flush=True)
    finally:
        for process, stream, *_ in running:
            if process.poll() is None: process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
            stream.close()
        data = summary(results, planned, time.perf_counter()-started, interrupted,suite=args.suite,discovered=discovered)
        (folder/'summary.txt').write_text(final_report(data),encoding='utf-8')
        (folder/'summary.json').write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')
    print(f'\n{args.suite.upper()} {"PASS" if data["successful"] else "INCOMPLETE / FAIL"}: '
          f'{data["tests_run"]} tests; {data["modules_completed"]}/{data["modules_planned"]} modules; '
          f'{data["failures"]} failures, {data["errors"]} errors, {data["skipped"]} skipped.', flush=True)
    print(final_report(data),flush=True)
    print(f'Text summary: {folder / "summary.txt"}',flush=True)
    print(f'Summary: {folder / "summary.json"}', flush=True)
    return 130 if interrupted else (0 if data['successful'] else 1)


if __name__ == '__main__':
    raise SystemExit(main())

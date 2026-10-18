# Baseline-backed test worlds

Feature tests should restore an isolated prepared baseline, rather than recreate the same world for every case. `WorldBaseline` stores a private in-memory SQLite snapshot; `baseline_world` owns it per test class and worker process. Each restore gets a new temporary directory, new database, and deep-copied public fixture attributes. SQLite backup includes committed WAL data. Test cleanups and unittest bookkeeping are never copied. Class cleanup closes the snapshot and removes the preparation save.

This increment applies the reusable baseline to all ordinary SupportWorld callers, defense/support, maintenance (including maintenance activation), manufacturing, production, and the extended catalogue fixture. Initialization, registration and migration tests still exercise their actual entry points. Other independent fixture families have not yet been migrated; this is not a claim that every suite now uses a baseline. Baselines are generated from current rules once per class, rather than checked-in database files that could silently become stale.

Catalogue progression retains every building/level, spending, work, health, release and repeat-completion assertion. It now reads the three before-cost fields directly and reuses the returned staffed snapshot rather than loading the entire state twice more. Manufacturing retains the complete 200-step offline comparison and original game durations.

No tests were run. Static AST checks confirmed syntax and retention of all existing test method names in edited modules. One clone-isolation regression test was added. The parallel runner automatically discovers it; its final pass/fail report and coverage selection are unchanged. Runtime improvement is unmeasured until the next user-run suite.

Run the same full command when ready:

    python -X utf8 run_tests_parallel.py --suite full --workers 2 --include-ui

These changes affect test fixtures only; the game, admin and bot processes need no restart.


## Second baseline increment

Structural combat and citizen-consequence baselines now include their feature activation once per class. Shared CombatWorld consumers, citizen combat, trading, social gameplay (including its borrowed market/expedition setups), and waiting-lobby test worlds now use private baseline copies. A callable preparer supports suites that borrow setup methods without inheriting the original test class. Original real account registration is performed when preparing trading/lobby baselines, preserving their stored credentials. Flask authentication, live HTTP registration, initialization and migration test bodies remain unchanged.

The baseline is lazy: its one-time construction is included in the first test's recorded time; later cases only restore it. Module totals are therefore more useful than comparing that first test in isolation. No runtime savings are claimed before the next user-run measurement. All existing method names and assertion-call counts in edited modules were checked statically. A borrowed-fixture isolation test was added; it has not been run.

# Bounded catalogue fixtures — October 17, 2026

The previous full run spent about 103 seconds in the catalogue upgrade test.
Inspection showed that each subcase cleared older buildings but retained their
rows, completed jobs, worker histories and events. Later cases therefore loaded
progressively larger snapshots although each case is an independent contract.

The test now captures its fully initialized disposable world once into a private
in-memory SQLite baseline and restores that baseline before each building/level
case. SQLite backup preserves the complete committed database (including WAL
content); this is not a raw filesystem copy. All fixture connections close before
each restore. Each test/worker owns its own baseline and save.

Every catalogue item and upgrade level is still visited, with the same real
upgrade/builder commands and completion calls. All assertion expressions and loop
iteration ranges were compared statically and preserved. Costs, work duration,
level/status, HP ratio, worker release and idempotence checks are unchanged.
No production functions are mocked and no gameplay rules are changed.

Two small regression cases cover repeated reset isolation, foreign-key enforcement
and committed WAL capture. The new module is automatically included by full-suite
discovery; the quick suite remains its explicitly curated selection.

No tests or timing benchmarks were run. This bounds fixture growth but does not
establish the size of the speedup. The owner should measure the module again:

    python -X utf8 -m unittest discover -s tests -p test_building_catalogue.py
    python -X utf8 -m unittest discover -s tests -p test_fixture_baseline.py

The full runner will record updated timings in its usual summary:

    python -X utf8 run_tests_parallel.py --suite full --workers 2 --include-ui

This change optimizes the test fixture, not saved-game history processing. If live
world histories become expensive, production code needs separate profiling.

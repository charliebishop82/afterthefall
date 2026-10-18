# Civilian construction fixture optimization — October 17, 2026

The previous full-run log recorded about 85 seconds in the civilian construction
and upgrade sweep. Its loop retained demolished buildings, completed jobs and
history across independent building types, and advanced one cumulative clock.

The sweep now snapshots its initialized, funded prototype_v4 fixture once using
the existing private SQLite baseline helper. Each building starts from that same
baseline at game time 1000. Restores happen only between building types: every
individual building still undergoes initial construction and each upgrade in
sequence, using the real commands, assigned citizen, pause/resume controls and
the full configured elapsed build duration. No simulation or job code is mocked.

All original test methods, assertion expressions, iteration ranges and building
selection remain. Two additional guards check that building/job counts reset.
Source workbook comparisons, staffing, worker release and maximum-level rejection
are retained. Long offline and rollover tests elsewhere remain unchanged.

Tests were not run. Static Python parsing and assertion/loop comparisons passed.
This is an expected fixture saving, not a measured speedup. Gameplay code, the
player database, test selection and parallel-runner commands are unchanged.

Run the affected module (24 tests in the previous run):

    python -X utf8 -m unittest discover -s tests -p test_production.py

For comparable timings, use the same worker count and complete suite as before.
The entire previous module took about 148 seconds in the parallel full run;
85 seconds was the individual sweep, not the whole module. Standalone versus
parallel measurements have different CPU/disk contention.

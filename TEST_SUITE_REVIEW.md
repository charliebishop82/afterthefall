# Test suite review — October 17, 2026

> Subsequent implementation: after the owner stopped the active run, the first
> optimization increment was applied. It adds history-based slow-first scheduling
> (with an alphabetical override), slow-test summaries, shorter disposable HTTP
> shutdown polling, and plain Flask/equipment fixtures. All 893 pre-existing test
> methods and their assertion expressions were preserved by static comparison;
> five runner regression tests were added, giving 898 defined Python test methods.
> Equipment fixtures seed normal accounts/sessions instead of repeating password
> registration; dedicated authentication/security tests retain real hashing.
> No tests were run by Codex, and no runtime improvement or passing result has
> been claimed. Existing failures remain for the owner's next complete run.


## Scope and evidence

This was a static review of every Python test module, the shared fixtures, both
test runners and existing saved result files. No tests, game processes or bots
were launched. The owner's current test run was detected as active, so test
sources and runners were deliberately left unchanged. Only this review document
was installed. The AST inventory does not import tests or execute their bodies.

The current source contains **91 Python test modules, 893 directly defined test
methods, and 11 Node UI modules**. These are source counts, not a completed run or
a count of parameterized subcases. The shared fixture classes contain no tests.

## Main conclusion

There is no evidence that a large chunk of the suite is accidentally being run
twice. Exact normalized test-body comparison found **zero duplicate bodies**.
Saved worker reports contained **no identical test IDs across different modules**.
The source uses plain shared fixture classes rather than inheriting test classes.

That does not mean assertions never overlap. Service, HTTP, UI and legacy-version
checks intentionally cover related rules at different boundaries. Most runtime
comes from simulation scenarios and repeated world setup, not duplicate execution.
Combining files alone would not materially reduce the amount of simulation and
would reduce the parallel runner's scheduling flexibility.

## Measured history, not a new benchmark

The completed saved run `parallel-20261012T022359707160Z` recorded 811 tests in 81
modules and took **1,635 seconds (27.3 minutes)**. It was not successful. These
numbers predate recent simulation optimizations and new features; they do not
establish today's speed or pass/fail status. The newer run was still in progress
during this review and was not treated as a complete result.

The slowest modules in that historical run were:

| Module | Tests | Saved wall time |
| --- | ---: | ---: |
| test_defense_support.py | 33 | 238.4s |
| test_manufacturing.py | 19 | 197.2s |
| test_combat.py | 25 | 188.7s |
| test_structural.py | 32 | 183.7s |
| test_production.py | 24 | 178.7s |
| test_trading.py | 28 | 155.7s |
| test_citizen_consequences.py | 22 | 147.3s |
| test_building_catalogue.py | 6 | 137.8s |
| test_maintenance.py | 30 | 136.6s |
| test_population.py | 17 | 107.2s |

Older per-test reports identify whole-catalogue construction/upgrading,
manufacturing input-arrival boundaries, offline/incremental equivalence, and
midnight/expiry scenarios as important hotspots. Current measurements should be
collected from the owner's run before promising a speedup or shortening scenarios.

## Recommended increments

### 1. Improve scheduling and reporting first

The parallel runner currently launches modules alphabetically. Use the most recent
valid saved durations to run historically long modules first. Unknown modules
should receive a neutral estimate and deterministic ordering; missing or invalid
history must fall back safely. Continue discovering every new test automatically.

This reduces the chance of one long module being left on its own at the end.
It preserves each module's separate process, logs, report, tests and failure
details. It cannot make the slowest indivisible test itself faster. Do not claim
an ETA from historical data as a guaranteed finish time.

The final report could also list the ten slowest modules/tests, process startup
overhead and scheduling order. The existing TimedResult already captures test
durations including setup/cleanup, so no new dependency or test instrumentation
is needed. An optional module timeout and current-test heartbeat would make hangs
easier to diagnose; timeout should be configurable rather than silently skipping
long scenarios. Interrupted or timed-out modules must remain failures/incomplete.

### 2. Remove fixture overhead without removing coverage

Several HTTP test fixtures start serve_forever without a poll_interval. Python's
default shutdown polling interval is 0.5 seconds. Prototype and simulation fixtures
already use 0.01 seconds. Apply the same short polling interval to the other
disposable HTTP servers, leaving real server and HTTP assertions intact. This
cuts idle teardown waits; the exact saving needs a new run. Ensure shutdown,
server_close and thread joins remain registered in the correct cleanup order.

Move reusable Flask client/lobby/account helpers to a plain fixture class in
tests/fixtures.py. Equipment tests currently borrow FlaskTests helpers, and bot
equipment tests borrow EquipmentMarketTests helpers. This chain is not executing
those other test classes twice, but it makes unrelated tests harder to maintain.
Similar fixture borrowing appears in social/market/expedition/performance tests.
Extract helpers rather than making one TestCase subclass another TestCase.

Non-authentication scenarios can seed fixture accounts and issue normal sessions,
as existing shared HTTP fixtures already do, instead of repeatedly going through
password registration. Keep real registration, login, hashing, rate-limit,
session-revocation and authorization tests unchanged. Sixteen source modules call
accounts.register directly, with additional calls through borrowed helpers.
Production password hashing must retain its real 600,000 iterations; do not turn
it down globally or mock verification in security tests.

Pure configuration, parser and decision tests should live in classes with no
database/server setup. For example, the Garden's catalogue-only test currently
pays for a two-settlement SupportWorld in setUp, and equipment parser/config tests
pay for Flask app/database setup. Move just those cases into lightweight classes,
retaining their assertions and including them in full discovery.

Every mutable test world must remain isolated. Do not share a class-level writable
SQLite save merely to save setup time. A later optimization could build an
immutable per-worker baseline and use SQLite backup into a fresh temporary save
per test, but only for appropriate fixtures. Database creation, migration,
registration, seeding, uniqueness and deterministic-clock tests must retain fresh
initialization paths. Never copy a live database file while ignoring its WAL.

### 3. Consolidate organization selectively

Garden Oxygen and general Food Oxygen tests could share a feature module and a
plain fixture while retaining Garden cost/legacy/exposure checks and powered-crop
failure checks. This would mostly improve organization, with a small process
startup saving. Likewise, market pool/reserve/equipment helpers could share a
fixture module without merging all market tests into one large scheduling unit.

Do not delete the apparent catalogue overlap automatically:

- ProductionTests covers construction plus upgrades through the normal elapsed
  simulation in an earlier supported configuration.
- PopulationTests covers independent housing construction/upgrades and allocation.
- BuildingCatalogueTests checks current destination costs, work, preserved damage,
  worker release and exactly-once completion, using direct job progress.

These exercise different versions and paths. Configuration versions 1–13 remain
supported, so legacy behavior is still part of the regression contract. If the
product later drops old saves, removing that compatibility coverage is a separate
decision, not a speed optimization to apply silently.

### 4. Profile and split the actual long scenarios

Keep offline-versus-incremental and boundary-crossing tests: they protect precisely
the clock, production, storage and catch-up behavior that has caused real issues.
Do not patch away _advance, shrink all time spans, or remove comparison paths just
to get a faster suite.

For expensive whole-catalogue loops, consider individually scheduled parameter
cases or separate feature groups so more workers can help. Preserve fresh state,
all building/level combinations, resource-cost assertions, and the same rule
boundaries. Splitting into more fixtures can itself cost time, so measure before
and after. Existing subTest loops run serially inside one worker regardless of
--workers. Read-only workbook extraction could be cached within a process, while
retaining source-authority checks and fresh mutable configuration snapshots.

## What should stay

- Full-suite discovery and every existing behavioral assertion.
- Atomic rollback, ownership, rejected-action and Credit reservation coverage.
- Real Flask/Waitress/legacy HTTP boundary tests where they check distinct paths.
- Real security tests, deterministic clocks/seeds, and independent temporary saves.
- Python plus optional Node UI tests, with a clear failure if Node is requested
  but unavailable. No pytest or additional dependency is needed for these changes.
- Complete pass/fail summaries and failure tracebacks; focused runs must never be
  presented as a full-suite pass.

Nine methods have no direct assertion in their own body, but inspection confirmed
that they call assertion-bearing helpers (database constraint rejection or request
clock ordering). They are not empty tests and should not be deleted on that basis.

## Practical recommendation

Finish the current run without editing its code. Keep its summary.json and module
logs as a baseline. Implement increment 1 and the low-risk parts of increment 2,
then have the owner run the same complete suite with the same worker count and
compare timing and coverage. Only then decide whether splitting simulation cases
or consolidating more fixtures is worthwhile.

Two workers remain a conservative default. Four can improve throughput if the
machine has spare CPU/RAM, but more workers can contend with the running game,
bots, SQLite filesystem writes and password hashing. Do not assume doubling workers
halves runtime. Different temporary databases avoid cross-test save sharing, but
they still compete for the same disk. Test fixtures use system temporary folders;
moving the source repository alone does not relocate those databases.

The detailed testing guide contains a stale introductory count of 38 modules /
617 tests. Replace fixed current-count claims with the current runner report or a
dated source inventory; retain historical increment results clearly as history.

## Complete Python module inventory

Counts below are directly defined source methods, not executed test results.

| Module | Test methods | Source lines |
| --- | ---: | ---: |
| test_accounts.py | 19 | 149 |
| test_admin_controls.py | 22 | 345 |
| test_admin_hosting.py | 15 | 202 |
| test_admin_player_logs.py | 5 | 91 |
| test_admin_suite.py | 10 | 120 |
| test_allied_expansion.py | 3 | 52 |
| test_auto_builder.py | 5 | 58 |
| test_background.py | 10 | 126 |
| test_background_progress.py | 4 | 40 |
| test_banking.py | 12 | 106 |
| test_bot_audit.py | 5 | 78 |
| test_bot_combat.py | 8 | 89 |
| test_bot_equipment.py | 17 | 195 |
| test_bot_expeditions.py | 7 | 57 |
| test_bot_market.py | 10 | 87 |
| test_bot_market_snapshot.py | 3 | 61 |
| test_bot_runtime.py | 8 | 76 |
| test_build_map_feedback.py | 4 | 37 |
| test_building_catalogue.py | 6 | 93 |
| test_buildings.py | 26 | 371 |
| test_catchup.py | 5 | 83 |
| test_catchup_calculations.py | 11 | 167 |
| test_catchup_http.py | 3 | 46 |
| test_citizen_consequences.py | 22 | 183 |
| test_citizen_identity.py | 5 | 71 |
| test_citizen_portal.py | 3 | 22 |
| test_combat.py | 25 | 265 |
| test_database.py | 20 | 260 |
| test_defense_display.py | 3 | 30 |
| test_defense_support.py | 33 | 246 |
| test_derelict_yields.py | 3 | 37 |
| test_economy_bots.py | 8 | 80 |
| test_equipment_market.py | 12 | 168 |
| test_expansion.py | 22 | 245 |
| test_expansion_http.py | 2 | 34 |
| test_expedition_display.py | 4 | 24 |
| test_expeditions.py | 11 | 97 |
| test_expeditions_http.py | 1 | 26 |
| test_feature_http.py | 2 | 53 |
| test_flask_playtest.py | 24 | 361 |
| test_food_oxygen.py | 3 | 43 |
| test_garden_oxygen.py | 3 | 40 |
| test_idle_scavenging.py | 4 | 53 |
| test_legacy_defense_rendering.py | 3 | 31 |
| test_live_values.py | 3 | 40 |
| test_maintenance.py | 30 | 294 |
| test_manufacturing.py | 19 | 234 |
| test_map_attention.py | 3 | 27 |
| test_map_project_markers.py | 4 | 41 |
| test_market_pool.py | 8 | 85 |
| test_market_reserve.py | 6 | 84 |
| test_material_market_links.py | 2 | 17 |
| test_midseason_enrollment.py | 5 | 68 |
| test_military_portal.py | 2 | 27 |
| test_needs.py | 14 | 153 |
| test_offline_cap.py | 8 | 118 |
| test_operator_dashboard.py | 5 | 58 |
| test_parallel_runner.py | 8 | 77 |
| test_passive_map_staff.py | 3 | 25 |
| test_performance.py | 4 | 32 |
| test_player_guide.py | 5 | 68 |
| test_player_logging.py | 5 | 107 |
| test_population.py | 17 | 270 |
| test_production.py | 24 | 311 |
| test_production_storage.py | 12 | 158 |
| test_progression.py | 19 | 152 |
| test_prototype.py | 16 | 212 |
| test_quiet_catchup.py | 9 | 155 |
| test_recovery.py | 20 | 235 |
| test_renewable_opening.py | 1 | 54 |
| test_renewable_scrap.py | 8 | 90 |
| test_repairs.py | 21 | 158 |
| test_request_clock_order.py | 3 | 78 |
| test_request_performance.py | 1 | 16 |
| test_resource_alerts.py | 5 | 51 |
| test_review.py | 8 | 141 |
| test_review_completion.py | 19 | 248 |
| test_runner.py | 6 | 80 |
| test_saved_rankings.py | 2 | 40 |
| test_scavenging_map_marker.py | 3 | 30 |
| test_scoring.py | 11 | 83 |
| test_simulation.py | 19 | 230 |
| test_social.py | 22 | 295 |
| test_staffing_highlights.py | 3 | 26 |
| test_state_reuse.py | 3 | 61 |
| test_step_diagnostics.py | 6 | 54 |
| test_storage_display.py | 3 | 31 |
| test_structural.py | 32 | 303 |
| test_trading.py | 28 | 327 |
| test_ui_citizen_counts.py | 3 | 26 |
| test_work_overview.py | 4 | 60 |

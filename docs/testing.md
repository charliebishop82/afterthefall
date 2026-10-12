# Regression testing



See [the current feature coverage and review](current-game-review-2026-10-11.md).

The numbered increment sections below preserve historical results, not the latest test count.



Every feature adds tests, and all earlier tests remain part of the full suite.

A completed increment requires the full suite to pass. Tests reduce regression

risk; they do not prove that every possible defect has been excluded.



## Conda handoff workflow

**Owner instruction: Codex must not run any tests unless explicitly asked.**
This includes focused checks and the full suite. Codex still writes tests and
provides commands; checks that have not been run remain pending.




Codex maintains code and tests and runs tests only when explicitly requested. The user runs the full

suite and manual playtests in their dedicated Conda environment. Full validation

remains pending until the complete result is available; a focused pass is not a

full-suite pass. See [Running the game](../RUNNING_THE_GAME.md) for setup,

server restarts and the default division of work.



All test modules live in the project `tests/` directory (currently 38 test modules and

617 tests). They use temporary saves. Some checks also read the workbook in

`sources/`; keep the read-only references beside the code when copying the project.

No pytest, spreadsheet application or document package is required for tests.

Install the project `requirements.txt` into the activated Conda environment.



```powershell

conda activate settlement-game

Set-Location 'C:\Users\charl\OneDrive\Desktop\multiplayer war game'

python -X utf8 run_tests.py 2>&1 | Tee-Object -FilePath test-results.log

$LASTEXITCODE

```



Replace `settlement-game` with your environment name. Success is `OK` and exit

code `0`. Save the full failure traceback and `test-timings.json` when reporting

problems. Restart the affected server after edits before testing changed browser

behavior; the automated suite can run with the servers online.



## Run all tests (alternative project .venv)



From the project folder:



```console

.venv/Scripts/python.exe run_tests.py

```



On this computer, from any folder:



```powershell

& 'C:/Users/charl/OneDrive/Desktop/multiplayer war game/.venv/Scripts/python.exe' 'C:/Users/charl/OneDrive/Desktop/multiplayer war game/run_tests.py'

```



The runner discovers `test_*.py` files in `tests/`, prints each result, and returns

an unsuccessful exit status on failures, import errors, or an empty suite. Use

`__init__.py` in any future nested test directories so discovery includes them.

No external testing framework is needed. Install requirements.txt in .venv for the Flask transport tests.



## Original database baseline (historical)



The 20 existing database tests cover creation, integrity, overwrite refusal,

foreign keys, numeric limits, ownership and season constraints, active work and

combat commitments, retained history, and rollback of failed transactions.

These were the initial database-only checks. Current gameplay coverage is listed in the complete review and later regression sections below.

Tests create temporary databases and must never modify `database/game.db`.



## Original prototype acceptance checklist (now covered by regressions)



| Feature | Required behavior checks |

| --- | --- |

| Starting settlement | Town Hall, six citizens, configured supplies, no duplicate initialization |

| Resource simulation | Production and consumption over elapsed time; zero resources; storage boundaries; processing the same timestamp twice |

| Building placement | Valid placement; occupied or out-of-map footprint rejected without spending resources |

| Construction | Materials charged once; work progresses correctly; no progress without workers; completion applied once |

| Housing | Capacity changes correctly after construction and reload |

| Persistence | Save, close, reopen, and continue from the same authoritative state |

| Browser actions | Valid actions update saved state; invalid actions leave it unchanged; displayed values reflect server results |

| Complete playable loop | Create settlement, advance time, construct housing, reload, and verify the result |



Retain these checks as the corresponding behavior evolves, using the agreed rules

and configuration. Do not implement a deferred system just to fill this table.



## Working method



1. Define the intended behavior and important failure cases for the increment.

2. Add focused tests alongside implementation. For a bug, reproduce it first.

3. Use explicit clock values, controlled random inputs, and temporary databases.

4. Run focused tests while working, then run the full suite before completion.

5. Investigate any old failure. Change an old expectation only for an agreed rule

   change, documenting that change rather than hiding a regression.

6. Report the test count, result, and remaining limitations.



Use real SQLite for database integration checks. Test interactions between features

as they become available, especially transactions and saved progress. When a UI

exists, also perform a browser smoke check of the main player flow; add automated

browser coverage when it is practical. Keep that tooling out of this first database

increment. Automatic testing on every code push can be connected when a repository

and its hosting are established.



## Prototype increment 1 verification



The suite now has 36 passing tests: the original 20 database tests and 16

prototype tests. The added checks cover workbook-backed starting values,

creation and rollback, duplicate/concurrent submissions, reopening saved changes,

HTTP validation and escaping, private-file access rejection, and server restart.



Browser verification on 2026-09-30: created New Avalon, inspected its map and six

citizens, followed Town Hall/roster links, reloaded, and restarted the server.

The saved settlement was preserved. Desktop and 390-pixel mobile layouts were

visually checked; the mobile page had no document-wide horizontal overflow.

Browser error logs were empty. Original game.db and source documents were unchanged.

## Prototype increment 2 verification



On 2026-09-30, all 55 tests passed: the previous 36 plus 19 resource simulation

and HTTP tests. Coverage includes elapsed-time production and consumption,

worker modifiers, storage limits, repeated timestamps, pause/resume, deadline

preservation, depletion, reassignment history, rollback, persistence, season end,

and invalid browser actions. Tests use temporary databases and controlled clocks.



A separate browser-test save verified starting time, automatic supply refresh,

changing the Administrator, pausing, and reloading without further consumption.

The 390-pixel mobile page had no document-wide horizontal overflow. The original

player save was verified logically identical to its pre-update backup and remains

paused. Health effects and construction remain deferred; resource depletion

pauses this prototype automatically.



## Food and Town Hall increment verification



On 2026-09-30, `.venv/Scripts/python.exe run_tests.py` passed all 81 tests in 80.392 seconds:

the previous 55 plus 26 Food/construction/upgrade tests. Earlier tests were not

changed. Coverage includes workbook values, placement and rotation, unlocks,

spending once, concurrent submissions, rollback, construction HP and completion,

manual staffing and worker limits, pause/offline boundaries, utility capacity,

production/storage, all Food upgrade levels, both Town Hall upgrades, and HTTP

validation. See food.md for the exact active scope and prototype interpretations.



Browser smoke checks used a disposable save: placed a Garden, assigned a builder,

started time, observed progress, completed construction, assigned a Food worker,

verified +6 Food/hour and total net +2, and paused. A funded test fixture then

verified the Town Hall upgrade, Greenhouse unlock, Greenhouse construction, and

Greenhouse upgrade screen. Completion fixtures were positioned one second before

completion; full real-duration arithmetic is covered by controlled-clock tests.

Desktop and 390-pixel mobile layouts were inspected without document-wide overflow.



The player save was backed up as database/prototype-before-food.db and verified

logically identical after installation; it remained paused. Source documents,

older configurations, and database/game.db were verified unchanged by SHA-256.



## Civilian production increment



On 2026-09-30, `python -B run_tests.py` passed all 105 tests in 276.179 seconds.

The original 81 tests are unchanged; 24 new tests cover the civilian catalog,

all construction and upgrade levels, utilities, material recipes and depletion,

shared storage, protected Food in unpowered Cold Storage, gradual scavenging,

transaction rollback, offline equivalence, and HTTP validation/private loot.



Browser checks used a disposable save on port 8766: enabled civilian production,

placed a Rain Collector, assigned a builder, started time, observed progress,

completed it with a one-second-before-completion fixture, and verified passive

+3 Water/hour. Assigned a scavenger to a safe ruin, observed gradual recovery,

and paused time. Browser error logs were empty. The player save was never used

for tests and matched its backup after installation. Source documents, original

database/game.db, old configurations, and old test files retained their hashes.

See production.md for the active scope and documented prototype assumptions.



## Housing and survivor increment



On 2026-09-30, `python -B run_tests.py` passed all 122 tests in 337.050 seconds

in the staging copy installed into this project. The previous 105 tests remain

unchanged. Seventeen new tests cover workbook housing values, independent types

and all their upgrades, unlocks, rollback, Oxygen/condition capacity, housing

priority, reassignment, survivor timing and history, increased consumption,

homelessness penalties, pause/reload/offline equivalence, and HTTP validation.



Browser checks used a disposable save: enabled v5, built a Shack, assigned its

builder, started time, verified completion and 12 total housing places, assigned

a scavenger, and observed a Level-1 survivor join at a controlled discovery

boundary. The new citizen appeared unassigned with 75 HP; all seven citizens

received housing. Test fixtures positioned construction/discovery one second

before their boundary; real-duration arithmetic is tested with controlled clocks.

Desktop screenshots and the 390-pixel layout were inspected, with no document-wide

horizontal overflow or browser error logs. The player save was backed up before

installation and source documents, previous configurations and old tests retained

SHA-256 hashes. See housing.md for the active scope and deferred effects.



### Citizen recovery and housing morale (2026-09-30)



Full regression suite: 142 tests passed in 232.321 seconds, including all 122 prior tests and 20 new recovery checks. Browser verified explicit activation, current housing morale, and running/paused recovery status on a disposable save. Existing player save and source documents preserved; pre-install SQLite backup created under database/backups.





### Citizen progression (2026-09-30)



Full suite: 161 tests passed in 188.142 seconds, including all 142 previous tests and 19 new XP/leveling checks. Tests cover workbook thresholds, actual crew work, stalled production, health/morale scaling, pauses, offline equivalence, level history and cap, rollback, season finish, and HTTP activation/restart. Browser preview on a disposable save confirmed XP display, automatic level 2 and 108 maximum HP with current HP preserved. Source files, previous configurations and regression tests remain unchanged. A pre-install SQLite player backup is stored in database/backups.





### Building repairs (2026-09-30)



Full suite: 182 tests passed in 221.364 seconds, including all 161 prior tests and 21 new repair checks. Covers material costs, duplicate and invalid actions, completion and repeat repair, repair XP, crew diminishing returns, utility safety, current production and housing, Town Hall regeneration, pause/offline equivalence, season finish/suspension, transaction rollback, and HTTP activation/restart. Browser preview confirmed 900 to 921 Town Hall HP over an hour with one repair worker plus regeneration, 2 worker XP, and staffing/release controls. Source documents, prior tests/configurations and player save preserved; pre-install SQLite backup stored in database/backups.





### Account foundation (2026-09-30)



Full regression suite: 201 tests passed in 297.461 seconds, including all 182 previous tests and 19 new account checks. The focused 19-test suite also passed against the final account UI. Checks cover salted password hashes, registration/login/logout, throttling, session rotation/expiry/restart, CSRF/origin checks, foreign citizen/building/derelict rejection, thread isolation, shared geography/private loot, late joins, Bank starting-transfer balances, and individual supply freezes with matching live/UI state. Browser verified registration, separate settlements, logout/login and saved state using disposable accounts. Original save, source documents and previous tests/configurations preserved; account play uses a separate database/accounts.db.





Private trading regression coverage: tests/test_trading.py verifies workbook rules, atomic resource and Credit transfers, reservation accounting, ownership, duplicate/concurrent actions, rejection/cancellation/expiry, final-window and season-end behavior, storage limits, supply freeze recovery, construction/repair/converter interactions, and authenticated HTTP forms with live updates. All fixtures use disposable databases and controlled clocks.



### Private trading (2026-09-30)



Full suite: 229 tests passed in 442.385 seconds, including all 201 previous tests and 28 new trading checks. Browser verification exchanged 10 Scrap for 5 Credits between two disposable players, confirmed exact balances and paired Credit audit entries, and left no active reservations. Both player databases are backed up before installation; no test or demo data is copied into them. Earlier tests, source documents and versioned balance configurations remain unchanged.



Citizen raid coverage: tests/test_combat.py exercises source values, war warnings, protection, the six-home floor, health/integration/ownership, away accounting, timed and sequential resolution, injuries/deaths/XP, loot and trade reservations, storage overflow, system recalls, midnight reset/population recovery, private reports, rollback and HTTP authorization. All fixtures are disposable and clocks controlled.



Consistency review coverage: tests/test_review.py reproduces supply-freeze commands

that previously changed staffing or started construction/scavenging after catch-up

froze the settlement. It verifies all-player season finalization, frozen-player job

cancellation, exact-end raid resolution, post-end recall/refund idempotence, and

unique survivor arrivals without renaming or duplicate processing. Prior tests are

preserved unchanged; all scenarios use disposable saves and controlled clocks.



### Citizen resource raids (2026-09-30)



Full regression suite: 254 tests passed in 704.735 seconds, including all 229 previous tests and 25 new combat checks. Disposable browser accounts verified the war warning, anonymous incoming countdown, deployed citizen availability, timed resolution, approved HP injuries, and private readable reports. Both player saves are backed up before installation; demo data is excluded.





### Consistency review (2026-09-30)



Full regression suite: 262 tests passed in 750.917 seconds, including all 254 previous tests unchanged and eight new review checks. Both existing saves passed read-only SQLite integrity and foreign-key checks and contained no duplicate citizen name groups. Source documents and prior balance configurations remain unchanged. Player saves are backed up before installing the reviewed corrections.



### Supply consequences and military production (2026-09-30)



Full regression suite: 297 tests passed in 1006.499 seconds, including all 262

previous tests unchanged and 35 new checks. The final strengthened 14-test supply

suite also passed in 71.203 seconds, explicitly confirming home citizens lose

health while deployed raiders do not.



New coverage adds 14 supply tests, 19 manufacturing tests and two authenticated

HTTP tests. Supply checks cover approved grace periods, combined and partial

shortages, current ration morale, reserved resources, healing, offline equivalence,

death history, population recovery, and home versus deployed citizens. Manufacturing

checks cover current workbook values, all six outputs, building upgrades, exact

spending, batch order/repetition, utilities/workers, XP, reserved storage, trade

reservations, incoming materials, ownership, late joins and season finalization.



Disposable browser accounts verified ration morale restoration, two completed

Offensive Drones with exact material spending, live batch progress, shortage health

loss while time continued, and restored supply stopping loss and resuming healing.

No test or browser fixture is installed into either player database. Prior tests,

source documents and older versioned configurations remain unchanged.





### Support, guards and drone combat (2026-10-08)



Final focused feature suite: 33 tests passed in 278.023 seconds.



New regression coverage in tests/test_defense_support.py uses disposable databases

and controlled clocks. It covers workbook costs/bonuses, activation and late joins,

owned/exclusive guard-patrol staffing, operational radius, medical needs/capacity/

power, current non-stacking community morale, optional power, engineering work,

scavenging yields, distinct Oxygen/Electricity medical priorities, offline equivalence, public construction/upgrades, drone-only

and mixed raids, air-before-resource phases, ground-defense eligibility, persistent

HP/destruction, storage release, bad/foreign/duplicate units, deployed citizens,

recalls, season end, private reports, CSRF/origin and duplicate HTTP fields.



Disposable browser verification staffed and released guards/patrols, staffed a

Clinic and Community Center, displayed 2.50 HP/hour treatment and +3.75 current

morale, and resolved a two-drone raid through automatic air defense. Both drones

returned at 80 HP and delivered exactly 40 Scrap. Restarting the final-code preview preserved

assignments, modifiers, healing, drone HP, balances and the private report.

Screenshots confirmed readable

support controls, defense radii and expanded private phase reports. No demo data

is installed into player saves; sources, earlier configurations and tests remain

unchanged.



Full regression suite: .venv/Scripts/python.exe run_tests.py — 330 tests passed in 1790.470 seconds.







### Drone maintenance and voluntary building removal (2026-10-08)



Focused maintenance suite: 29 tests passed in 154.775 seconds. An additional

automatic Town Hall funding rollback regression passed in 5.390 seconds.



New disposable-save coverage checks version activation and late joins, source-rate

refunds and demolition recovery, accumulated investment history, worker release,

footprint reuse, storage overflow, stored military assets and trade reservations,

inaccessible Cold Storage food, owned drone/workshop selection, paid service and

restart equivalence, workshop outages, manual/automatic Repair Drone targets,

health-scaled contribution, affordability, one-time charges, sequential targets,

manual-order completion, atomic rollback of unaffordable automatic Town Hall

repair attempts (including pending regeneration credit), no drone-derived citizen XP, pause/final-window/season-end

boundaries, rendering, CSRF, origin and duplicate HTTP fields.



Disposable browser verification serviced an Offensive Drone from 80 to 90 HP in

one simulated hour and to 100 HP on completion. Automatic Repair Drone work

restored a Garden from 100 to 150 HP. Cancelling a 0%-progress Garden returned

31.5 Scrap; confirmed demolition recovered 14 Scrap and removed the Garden from

the map. The same assignments, paid projects, completed health and removal state

were reopened after restarting the final-code preview. No demo data is installed.



Full regression suite: .venv/Scripts/python.exe run_tests.py — 360 tests passed in 1620.841 seconds.





The structural/citizen increments add regression coverage for finite ammunition,

interception, private reports, raid objectives, destroyed storage/factories, occupant

injuries, chain explosions, progress-preserving damage, ruin salvage and rebuilding,

Oxygen warnings and evacuation, grace periods, births/departures, owner isolation,

HTTP form validation, and paused/offline clock boundaries. All tests use temporary

saves. Run the complete suite with `.venv/Scripts/python.exe run_tests.py` before installing changes.



Social-feature regressions in `tests/test_social.py` cover atomic partial fills, Credit/Bank conservation, reservations shared with direct trades, fee order/floor/rounding, storage and availability, concurrent buyers, rollback, season settlement, treaty roles/expiry/cooldowns/inbound recalls, mail isolation/read/archive persistence, escaped text, rate limits, board moderation/audit, notifications and authenticated HTTP/CSRF/origin/duplicate-field validation. Run `.venv/Scripts/python.exe run_tests.py` for the complete suite.





## Shared fixtures and timing reports



`tests/fixtures.py` owns the shared Support, Combat and authenticated HTTP worlds.

They are ordinary helpers, not discoverable test classes. Each use creates its own

temporary database and registers cleanup with the owning test. Feature assertions

remain in the original test methods. Fixtures are currently used by combat,

support, maintenance, structural conflict, citizen consequences and expansion

checks; older unrelated setup remains unchanged for incremental consolidation.



`python run_tests.py` still discovers and runs every test. It now prints the ten

slowest tests and writes `test-timings.json` beside the runner. Timings include

setup, the test body, teardown and cleanup, measured with a monotonic clock.

The JSON contains each test's outcome/time and totals by module. It is generated

output and is ignored by Git. Use these measurements before simplifying expensive

fixtures; merely merging files does not reduce simulation work.



```powershell

python -X utf8 run_tests.py --slowest 20

python -X utf8 run_tests.py --timings custom-timings.json

```



`--slowest 0` hides the slowest-test list but still runs all tests and writes the

report. A report write failure is reported and returns an unsuccessful exit status.

The runner retains unittest failure, error, skip and subtest behavior. Six focused

runner regressions verify timing and outcome handling. Together with the fixture

check below, the suite has 557 checks; all 550 original test assertions remain.



A previously random admin construction fixture is now seeded: an occupied

garden plot was reproduced with map seed 00000000000000000000000000000006.

Seed 00000000000000000000000000000001 keeps the intended plot clear. A seventh

new regression checks the fixture; all 550 original assertions remain unchanged.



Verification: the full 557-test suite passed in 1791.444 seconds. The original

550 test bodies were compared structurally and preserved exactly. The slowest

measured check was midnight Bank-interest/attack ordering (99.176 seconds).

This refactor centralizes setup; it does not claim a major runtime reduction.



## Current review validation — 11 October 2026



The full 612-test suite passed in 1746.668 seconds. All 37 existing test files were preserved byte-for-byte; 19 new review regressions cover the corrections and new Advisor/operator investigation controls. Focused structural, support and review validation also passed all 84 checks. See [the current review](current-game-review-2026-10-11.md) for the no-grants Hall 3 campaign, tested rule choices and remaining acceptance work. Historical counts above describe earlier releases.


## Player request logging increment: awaiting owner validation

Five tests were added in `tests/test_player_logging.py` for UTC/request correlation,
clock-error metadata, credential/query/path exclusion, sanitized unexpected errors,
and bounded log rotation. Existing tests are unchanged. No tests were run by Codex,
as requested. The suite now contains 622 tests if discovery succeeds.

From the activated Conda environment and project folder:

```powershell
python -X utf8 -m unittest discover -s tests -p test_player_logging.py -v
python -X utf8 run_tests.py
```

Manual check: restart the player server with the same save, reload the game, perform
an ordinary action and inspect `logs/player-actions.jsonl` for its account/target,
status and request ID. Check a naturally rejected action for its failure record.
Do not alter the live save clock to reproduce a clock fault. This increment adds
observability; it does not change the earlier-clock gameplay guards or fix the
reported concurrent-request race.

## Admin player-log viewer: awaiting owner validation

Five new tests in tests/test_admin_player_logs.py cover admin authorization,
filters/export and save isolation, missing/rotated files and path restrictions,
HTML escaping/incomplete records, and bounded newest-first reading. No tests were
run by Codex. Existing regression tests remain unchanged.

From the activated Conda environment:
    python -X utf8 -m unittest discover -s tests -p test_admin_player_logs.py -v
    python -X utf8 run_tests.py

Manual check: restart both servers with the same database. In the console open
Logs → Player requests and errors, reload after a player action, and inspect its
request ID, timestamp and result. Test counts and behavior await owner validation.

## Focused interface increment: owner validation pending

No tests, browsers or servers were run by Codex. Existing Python regressions
remain unchanged. Five geometry tests are in tests/test_placement_ui.cjs.
They use Node's built-in runner, if Node is available:
    node --test tests/test_placement_ui.cjs
Node is optional for these UI tests; it is not a game runtime dependency.

Owner acceptance: restart the player server with the same save; visit all six
views and check every system remains accessible. Click map buildings/ruins across
views; confirm target details open. Change building type/orientation and inspect
nearby full footprints; manually choose occupied land and map edges; inspect red
preview; ensure no preview spends resources. Submit a normal action and confirm
the view survives the redirect. Check keyboard navigation, narrow screens,
collapsed information, shortages and paused-state controls. Check live supplies
continue to refresh on every view. Run the Python regression suite when ready:
    python -X utf8 run_tests.py

This increment changes presentation only. The outstanding clock race remains
separate; successful UI behavior has not yet been validated by execution.

## Parallel Python regression tests

In your activated settlement-game environment, from the project folder:
    python -X utf8 run_tests_parallel.py --workers 2

Increase to --workers 4 if your machine remains responsive. One separate Python
process runs each test module, with up to the requested number active together.
No extra packages are required. Existing run_tests.py still runs the suite
sequentially and remains useful for comparison if a concurrency-only failure
appears. Parallel speedup depends on CPU, memory and disk; module progress is not
a precise percentage of total runtime because modules have different lengths.

The terminal shows each start/completion, pass/fail, finished test/module counts,
elapsed time and a heartbeat every 15 seconds. Failed-module output is printed
when it finishes. Full per-test output and timing JSON are stored separately for
each module in a new test-results/parallel-TIMESTAMP folder. summary.json combines
results and lists unfinished modules. Each run has its own directory; earlier
reports are retained. The sequential test-timings.json is not overwritten.

To watch a running module's output in another PowerShell window, substitute its
printed log path:
    Get-Content 'FULL-PATH-TO-MODULE.log' -Tail 20 -Wait

Ctrl+C stops worker processes and writes a partial summary; incomplete runs do
not pass. Exit code 0 means all discovered modules passed, 1 means failure, and
130 means interruption. Skip counts are included. Reports include exception
tracebacks from tests; they use disposable test data rather than the live save.

This runner covers Python unittest modules, including importable nested test
packages. It does not run the optional Node placement tests:
    node --test tests/test_placement_ui.cjs

The runner and five new report/discovery regression tests are unrun pending owner
validation. To check the runner helpers first:
    python -X utf8 -m unittest discover -s tests -p test_parallel_runner.py -v
Then run the parallel full suite and share its terminal summary or summary.json.

## Player refresh/action clock race correction: owner validation pending

The player log confirmed a Warehouse build at 1791752508 overlapping an automatic
refresh that committed simulation time 1791752509 before the build acquired its
transaction. The request used an obsolete timestamp and was rejected.

The player Flask application now serializes simulation page loads, resource
refreshes and POST handlers through one application lock, taking gameplay time
after waiting for that lock. This prevents these requests from advancing saved
time ahead of a pending action in the same server. Game validation, SQLite
transactions and genuine backward-clock guards remain unchanged. Help and other
non-simulation GET pages do not use this gate. Heavy simulation can make another
player wait: correctness comes first in this local prototype. Run one player
server per database; the gate does not coordinate independent server processes
or admin-suite operations. Pause before operator corrections as usual.

Restart only the player server with its same database command. The failed build
was rejected, so inspect your current buildings and retry after restart; restarting
does not reset the save. No tests, servers or live data edits were performed by
Codex. Three new controlled-overlap regressions await execution:
    python -X utf8 -m unittest discover -s tests -p test_request_clock_order.py -v
    python -X utf8 run_tests_parallel.py --workers 2

Manual check: build and assign scavengers while the normal five-second refresh
is enabled. Check request logs for successful results and action timestamps.

## Build affordability and map assignment feedback: pending owner validation

Unavailable construction choices are disabled and labelled with each missing
material and/or Town Hall unlock. An expandable requirements list gives the same
information. Spendable materials exclude trade reservations. The selected
building's cost is shown next to its controls, and the normal resource refresh
updates available choices. When no choice is available, construction is disabled.
These hints do not replace server validation or promise adequate utility coverage.

The map shows N assigned on the Town Hall, other buildings and scavenging sites.
Counts include direct assignments and active/paused project assignments, count
each citizen once, and exclude citizens away on raids. Assigned is a headcount,
not a claim that those workers are productive. Hover/tap through a structure to
inspect its existing management details. No occupancy, production or combat
rules were changed.

Restart only the player server with the same database command. No tests or
servers were run by Codex; four new Python feedback regressions await owner runs:
    python -X utf8 -m unittest discover -s tests -p test_build_map_feedback.py -v
    python -X utf8 run_tests_parallel.py --workers 2

Manual acceptance: inspect unavailable choices and shortages, reserve materials
in a trade, and confirm spendable stock drives availability. Let resources rise
past a construction price while the page is open, then check the choice becomes
available. With no affordable buildings, confirm no preview exception and no
active construction button. Assign/release builders, production workers and
scavengers; verify map counts after refresh and verify map tile placement still
ignores count labels. Check small-screen label readability.

## In-place live values: owner validation pending

Automatic five-second polling no longer reloads the document. Supplies (including
Credits), rates, existing citizen health/XP/morale/assignment cells, job progress,
timers, scores and map assignment counts update in place. Open info blocks,
scroll position and form drafts remain in the current document. Connection
failures retry automatically. Shortages and clock status are shown live.

Changes needing new controls, lists, housing assignments, map geometry or events
show Update panels. This explicit button reloads the panel document and restores
page/map scroll and open-info states where possible. It resets unsent forms;
finish or submit those first. New citizens/buildings/messages need this panel
update. Paused/finished seasons freeze existing gameplay controls immediately;
update panels after a resume for fresh enabled controls. Existing server checks
remain authoritative.

Restart only the player server with the same save, then refresh the browser once
to load the new script. No tests, live data edits or servers were run by Codex.
Three Python payload regressions and three optional Node display-policy checks
were added:
    python -X utf8 -m unittest discover -s tests -p test_live_values.py -v
    node --test tests/test_live_refresh.cjs
    python -X utf8 run_tests_parallel.py --workers 2

Manual acceptance: scroll down, open info and type a message; wait across health
or XP updates. Verify no jump or draft loss and that displayed numbers change.
Check Update panels only reloads on click and restores scroll. Complete a job and
confirm progress completion and the new-controls prompt. Verify pause/resume,
shortages, map counts, affordability and Credits updates.

## Map viewport controls: owner validation pending

The first map view frames Town Hall and additional Oxygen coverage rectangles
with two tiles of padding, clipped to map edges. This is a visual framing box,
not a new coverage rule. Later visits remember the view in browser-tab storage
for the settlement. Oxygen area resets that frame. Full map zooms out to all
tiles; Town Hall frames the Hall with three surrounding tiles. Zoom +/− changes
scale. Arrow buttons move the view. Pan map switches dragging on; switch back
to Place / inspect to click land or structures. Dragging does not place buildings.

With keyboard focus on the map, arrows pan, +/− zoom, and Home shows the whole
map. Ctrl+mouse-wheel over the map zooms; ordinary wheel scrolling stays normal.
Buttons and pan mode work with pointer/touch input. SVG coordinate conversion
keeps building placement in world tiles at every zoom. Zoom is remembered across
Update panels and reloads; no save or gameplay rules change.

Restart only the player server with the same database command, then refresh the
browser once. Codex ran no tests or servers. Five optional Node geometry checks
were added:
    node --test tests/test_map_zoom.cjs

Manual acceptance: check the first Oxygen frame, each reset button, zoom limits,
all four map edges, drag without placement, inspect links, touch controls and
keyboard controls. Place a preview at several zooms and ensure coordinates match
the tile clicked. Verify saved zoom after Update panels. Run Python regressions
when ready:
    python -X utf8 run_tests_parallel.py --workers 2

## Compact map controls

Map controls now sit over the upper-right corner of the map as a compact
two-row icon toolbar: +/− zoom, ▦ full map, O₂ Oxygen area, ⌂ Town Hall,
✥ pan toggle, and direction arrows. Hover labels and accessible names explain
each icon. Pan remains highlighted while active. A small lower-left badge shows
zoom and interaction mode. Explicit button sizes override the site's full-width
form-button styling. Touch controls are slightly larger. All map behavior and
saved data are unchanged.

This is a static CSS/JavaScript adjustment: hard-refresh the browser (Ctrl+F5);
no server restart is needed. No tests or servers were run. Owner visual check:
verify the toolbar is inside the map, fits on narrow screens, shows hover labels,
and all existing controls still work.

## Compact map people markers and project progress

Assigned citizens now appear as a tiny vector person plus a number, rather than
the word assigned. Hover descriptions retain the meaning. Construction, upgrades
and repairs show a percentage on the structure, updated by normal value polling;
completed jobs reach 100% until panels are updated.

Changing building type/orientation searches current full footprints for the
nearest empty site. Occupancy hints refresh with normal polling, including
newly occupied or cleared land. If a rectangular building cannot fit normally
but fits rotated, the orientation selector changes and the notice explains why.
If neither fits, coordinates clear and the notice explains the lack of space.
An automatically suggested site outside the current viewport is brought into
view. Empty space still does not guarantee utility coverage, materials or unlocks.

Restart only the player server with the same save, then refresh the browser.
Codex ran no tests or servers. Map marker/progress regression tests and two large
footprint geometry tests were added; old assertions about marker text now retain
their accessible assigned-citizens meaning in the hover description.
    python -X utf8 -m unittest discover -s tests -p test_map_project_markers.py -v
    node --test tests/test_placement_ui.cjs
    python -X utf8 run_tests_parallel.py --workers 2

Owner acceptance: inspect compact counts, assign/release workers, check project
percentages while time runs, and choose several larger buildings and orientations.
Check suggested coordinates, automatic framing, rotated-fit notice and no-site
handling without changing gameplay rules.

## Scavenging map progress

Active and paused scavenging sites now show a small vector pickaxe and amber
remaining-work bar. The bar shrinks as gradual recovery advances. Hover text and
the accessible label say Scavenging: N% recovered. This is job progress, not the
quantity retained in storage: bonuses and discarded overflow still obey existing
rules. Construction/upgrade/repair percentages are pale green, with different
shape and meaning. Scavenging updates through normal polling; completion empties
the bar without reloading. Update panels removes cleared sites when ready.

Restart only the player server with the same save, then refresh the browser.
No tests or servers were run by Codex. New display regressions await owner runs:
    python -X utf8 -m unittest discover -s tests -p test_scavenging_map_marker.py -v
    python -X utf8 run_tests_parallel.py --workers 2

Manual check: inspect a partially scavenged site, hover the icon/bar, wait for
progress and confirm the amber bar shrinks while building percentages rise.
Paused jobs retain their progress; unstarted sites have no progress marker.
Verify completion and map clicks still work.

## Final parallel-run results and automatic new-test discovery

Each run discovers current test*.py modules; no fixed test list needs updating.
New Python tests join the next parallel run automatically. Importable nested
folders still require __init__.py. Keep new UI tests named test*.cjs.

The final terminal output lists every module as PASS, FAIL or INCOMPLETE, and
prints failed Python test names and tracebacks. Crashed workers and UI failures
include their log output and paths. summary.txt stores this readable report;
summary.json includes structured failure details. Reports and logs remain in the
run's unique test-results folder.

Python tests:
    python -X utf8 run_tests_parallel.py --workers 2
Python plus all automatically discovered JavaScript UI tests (Node.js installed):
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui

Node.js is required only for the optional UI tests, not for the game. If absent,
--include-ui explains the missing dependency before starting. Do not interpret a
Python-only pass as validation of the separate UI tests.

Three runner/report regressions were added. No tests or servers were run by Codex.
    python -X utf8 -m unittest discover -s tests -p test_parallel_runner.py -v

## Work ETAs and clearer menu summaries

Map build/upgrade/repair and scavenging work now shows a compact ETA, updated
through ordinary polling. It assumes current effective workers and conditions;
Waiting, Paused, Frozen or Ended replaces the estimate when appropriate.

Below the building cards, Active scavenging shows current crews, recovery
progress, ETA, gross Food/Water/material yield per hour, and recovered totals.
Yield uses current scavenging speed and material salvage bonuses. Recovered
totals are gross recovery before storage overflow, not net additions to the
stockpile. No workers means no current yield. Full site/crew management is
collapsed below this overview. Completion shows Done and zero current yield;
Update panels removes the completed card when ready.

Each of the six views has a short description and section shortcuts. Building
condition, outputs and staffing totals remain visible; staffing, upgrade and
repair actions are grouped behind an expandable control block. Scavenging follows
the building cards. No rules, costs or transactions changed.

Restart only the player server with the same database command and refresh the
browser. Codex ran no tests or servers. New Python regressions are discovered
automatically by the parallel runner:
    python -X utf8 -m unittest discover -s tests -p test_work_overview.py -v
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui

Owner acceptance: compare ETAs with job detail estimates, change crew size and
check estimates/yields update, pause the season, inspect shortages/overflow
wording, and open every menu/shortcut and building-management block. Check no
warnings or permanent-action confirmation is hidden or removed. Narrow-screen
visual acceptance and the full regression result remain pending.

## Live resource attention alerts

Overview includes Needs attention, updated by normal polling, and affected
resources show warning icons linking to it. The first increment covers empty
Food/Water, predicted shortages within two hours (including consumed materials),
Food/Water overflow, storage filling within one hour or above 90% while rising,
and one shared material-storage warning. Credits have no storage cap and are not
given false storage alerts. Times assume current effective rates. Paused/frozen
plans explicitly say When play resumes; these are forecasts, not historical
measurements of discarded supplies. Full material storage distinguishes paused
production from possibly discarded scavenging deliveries.

Alert links lead to ration, production, storage or scavenging controls. Urgent
shortages sort first; no pop-ups, notification writes or simulation rules were
added. Input/staffing/utility bottlenecks remain in existing building status and
Advisor panels, for a later alert increment.

Restart only the player server with the same database command and refresh once.
No tests or servers were run by Codex. Five new Python regressions join parallel
discovery automatically:
    python -X utf8 -m unittest discover -s tests -p test_resource_alerts.py -v
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui

Owner acceptance: inspect full Food/Water and shared materials, approaching-full
stores, shortages and paused season forecasts. Verify badges/links update and
disappear after conditions resolve; inspect small screens and the Overview menu.

## Military menu routing and combat onboarding

Combat sections now route by explicit system ID before heading text. Previously
Citizen and drone raids was incorrectly classified as citizen management, hiding
combat under Citizens. Military now includes the existing raid controls.
A prepare → declare war → launch guide explains the current process, with links
to equipment and citizens. No-target and no-eligible-force states have explicit
messages. No-factory production panels explain the infrastructure needed. No
combat requirements, timing, transactions or playable targets were changed.

Restart only the player server with the same save and refresh the browser.
Codex ran no tests, servers or attacks. New UI category regressions are picked up
automatically with --include-ui (Node.js required):
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui

Owner acceptance: open Military and confirm raid controls/guide are there, while
Citizens retains housing/recovery/wellbeing. Check no-target and no-force
messages, section shortcuts and factory instructions. Another active enrolled
settlement is required to exercise the existing war and raid flow. Do not reset
the save or create test opponents automatically.

## Mid-season enrollment

Active seasons now accept new accounts and settlement enrollment. New players use
the same starting citizens, supplies, catalogue and beginner protection as the
normal shared start, with no catch-up bonus. Their simulation/protection starts
at join time; the season end date remains shared. Existing settlements cannot
re-enroll or receive another starting grant. Names stay unique.

During an administrator-paused season, new players can reserve names without
creating a settlement or consuming supplies. Administrator resume creates their
normal settlements in the same transaction, at resume time. Suspended accounts
are excluded. Enrollment closes at finalization, including its time boundary
even if a season status update has not yet run; finalized/ended seasons reject it.

Restart both player and admin servers with the same database arguments. This
code change requires no reset or schema migration. Codex ran no tests or servers
and did not modify the live save. One old transport regression was updated for
the explicitly approved rule change (late joins now succeed); its check that an
unenrolled account cannot access gameplay remains. Existing shared-start,
duplicate-enrollment and other regression coverage remain.

New late-enrollment tests join parallel discovery automatically:
    python -X utf8 -m unittest discover -s tests -p test_midseason_enrollment.py -v
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui

Owner acceptance: register a new account in the running season, choose a unique
settlement name, and inspect normal starting supplies/protection. Check paused
reservation and administrator resume, duplicate submissions, and finalization
rejection. Automated tests use disposable saves only. Human/bot entry rules are
identical; bot creation and control are not implemented in this increment.

## Automatic first builder on placement

A build submitted through the player interface now assigns one eligible,
unassigned home citizen to the new construction job in the same transaction as
placement and payment. The lowest citizen ID is used for predictable selection.
It never takes the Administrator or another worker, assigns someone away/dead,
or authorizes exposed work. Normal safe Oxygen coverage is required. If no safe
eligible citizen is available, placement still succeeds with no builder, ready
for manual staffing. Upgrades and production-worker assignments remain manual.
Automatic staffing has its own game event and releases normally at completion.

The game service has an explicit auto_builder option, enabled by the player
build route; existing manual callers keep their behavior unless they request it.
Restart only the player server with the same save. No tests, servers or live save
edits were performed by Codex. New regressions are discovered automatically:
    python -X utf8 -m unittest discover -s tests -p test_auto_builder.py -v
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui

Owner acceptance: place a safe affordable building with a free citizen; inspect
one assigned builder and its map count/ETA. Try with no free citizens and outside
safe Oxygen: site remains unstaffed. Existing workers and the Administrator
should stay in their roles. Placement rejection must not assign or spend.

## Citizen counts in the sticky header

The supplies bar now includes total Citizens and Free citizens, both linking to
the roster. Total includes residents away on raids. Free means unassigned, home,
and above zero health; it does not promise adequate Oxygen or other requirements
for a specific job. Counts refresh in place with supplies, without reloading.
The eight tiles use one wide-screen row or two rows on narrower screens.

Restart only the player server with the same save, then refresh the browser.
Codex ran no tests or servers. New count regressions join parallel discovery:
    python -X utf8 -m unittest discover -s tests -p test_ui_citizen_counts.py -v
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui

Owner acceptance: assign/release a citizen and inspect Free citizens after the
normal refresh; inspect total after arrivals/losses and away residents. Verify
header links, sticky behavior and narrow-screen layout.

## Unstaffed building highlights

Buildings needing production staff but with no present assigned production worker
(or local Guard Post defender) have an amber border and Unstaffed label. Active
construction/upgrade/repair projects instead show Needs builders / Needs repair
crew when no present citizen is assigned to that job. Passive housing/storage
with zero worker requirements is not flagged. Existing assigned but ineffective
workers still use the building's normal operational-status explanation.

Highlights update in place with normal resource polling. Restart only the player
server with the same save, then refresh. Codex ran no tests or servers. Three new
staffing-feedback tests join automatic parallel discovery:
    python -X utf8 -m unittest discover -s tests -p test_staffing_highlights.py -v
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui

Owner check: release/assign a production worker and watch the border; inspect
zero-worker housing, an unstaffed construction site and a repair project.

## Concise menu layout

Player menu panels use smaller spacing, compact tables/cards, and inline form
actions instead of full-width buttons where space allows. On small screens,
labels stack again. Secondary explanations in military production, combat,
maintenance and progression are collapsed by default. Operational statuses,
numbers, warning messages and permanent-action confirmations remain accessible.
The map itself, its controls and placement behavior are unchanged.

This increment changes static CSS/JavaScript only. Ctrl+F5 loads it; no server
restart is needed. Codex ran no tests or browsers. Existing UI regressions remain
part of --include-ui discovery. Owner acceptance: open each menu and try keyboard
navigation through existing forms, resize the window, inspect hidden controls,
warnings and confirmation checkboxes, and ensure the map is unchanged.
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui

## Operator dashboard and read-only player inspection

The independent admin suite now has Dashboard, Players & maps, Logs,
Diagnostics, Season, Accounts, Corrections, Moderation, Audit and Bots pages.
Existing operator POST services, reasons, CSRF checks and frozen-state correction
requirements remain intact. Control sections are separated for easier navigation.
The dashboard shows counts, season boundaries, recent events and investigation
links. Player request logs are a readable table with expandable full records;
filters, rotated files and JSON export remain available.

Players & maps opens a committed read-only SQLite snapshot, with supplies,
citizens, buildings and a zoomable inspection map. It runs no simulation advance,
includes no player action forms/polling, and never impersonates the inspected
player. Only the current settlement for an account is supported by the existing
state reader; historical entries explain this limit. The Bots page explicitly
states that controllers are not installed; this increment implements dashboard
and inspection first, as chosen by the owner.

Restart the admin server only, retaining its database argument:
    python -X utf8 admin_suite.py --database database/playtest-fresh-01.db --port 8768
Then Ctrl+F5 at http://127.0.0.1:8768/. Your live database was not changed by
installation. No tests, servers or browsers were run by Codex. New operator-view
tests are discovered automatically by the parallel runner:
    python -X utf8 -m unittest discover -s tests -p test_operator_dashboard.py -v
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui

Owner acceptance: navigate each operator page, inspect a player map and confirm
no clock advance, review a failed request with full metadata, export logs, and
verify correction controls still require a freeze and reason. Bot execution is
explicitly deferred. Visual and full regression validation remain pending.

## Basic economy computer players

Restart both game and admin servers with the same database commands. The Bots
page now creates normal non-admin accounts/settlements and Start/Pause controller
controls. Creation is atomic and uses normal enrollment, resources, citizens,
protection and feature initialization; it provides no special grants. New
controllers start paused. Pre-launch/paused-season bots reserve names normally.
Their account passwords are randomly generated, hashed and not retained.

In a third activated Conda window, run one controller process for this save:
    python -X utf8 run_bots.py --database database/playtest-fresh-01.db --game-url http://127.0.0.1:8767

No extra packages. Enable one or more bots from the admin Bots page. The runner
takes one decision per bot about every 30 seconds, sequentially across bots.
It creates normal scoped player sessions, refreshes through /api/resources, reads
only that bot's own committed state, and submits authenticated player POST
requests with ordinary CSRF tokens. Sessions are removed after each step.
The runner verifies player/save identity and never follows request redirects.

Priorities: restore Administrator, staff construction, staff useful production,
build affordable missing economy infrastructure, provide storage/housing, upgrade
Town Hall and safely scavenge. It can release a scavenger to staff more urgent
work, preserves existing producers/Administrator, and never authorizes exposed
work. Sites vary through a stored seed plus decision number. The heuristic is
intentionally modest: it does not yet trade, manufacture equipment or attack.

The Bots page shows recent decisions, parameters, rejections and request IDs,
plus links to each bot's read-only map and ordinary player request logs. Up to
1000 decisions per bot are retained (latest 100 across bots displayed). Rejected
actions are logged and retried/reconsidered at normal decision intervals.
Unexpected errors remain visible, not silently treated as successes.
Stopping run_bots.py with Ctrl+C stops controllers only. Pausing a controller
prevents its next action; one already in flight may complete. Game time and
consumption continue for bot settlements just as for people. To freeze their
game state use normal account/season suspension/pause. Use one runner per save;
a crash can leave a claim waiting up to two minutes before retry.

No bots were created or run in the live save by Codex. No tests or servers were
run. New bot regressions join parallel discovery automatically. Begin with one
bot in a disposable playtest if possible and inspect its decisions and resource
warnings before enabling several. Economy heuristics are not proof of balanced
gameplay or a guarantee against shortages; they are intended to expose problems.
    python -X utf8 -m unittest discover -s tests -p test_economy_bots.py -v
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui

The earlier Bots-placeholder assertion is updated for the explicitly requested controller feature; all other operator regressions are preserved.

## Passive-building map markers

Completed buildings with zero operating worker slots no longer show a person
count. Their hover description says No operating staff required. Construction,
upgrades, repairs and active building salvage still show crew counts, even on
otherwise passive structures. The Town Hall and scavenging sites keep their
counts. A passive building's crew marker hides live when its project completes.
No staffing rules changed.

Restart only the player server with the same save, then refresh. No tests or
servers were run by Codex. New regressions join automatic parallel discovery:
    python -X utf8 -m unittest discover -s tests -p test_passive_map_staff.py -v
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui
Owner visual check: compare completed passive housing/storage, a staffed
production building, a passive construction site and a completed repair.

## Ground defense in the live header

Ground defense shows baseline local strength against a citizen raid at the Town
Hall, before randomness and allies. It uses current health/morale/level, the
existing 15% patrol bonus, eligible local Guard Post defenders, Town Hall occupants
when structural combat is enabled, ready ground-defense drones, Guard Post bonus
and operational automated turrets covering the Hall. Hover/focus on the link
shows component values and limitations; the link opens combat in Military.

This is not a universal rating or victory prediction. Air defenses/interception
operate separately; infrastructure raids can target elsewhere, and drone-only
attacks use different participation rules. No combat formulas changed.
The value updates in place. Restart only the player server with the same save
and refresh. Codex ran no tests or servers. New defense-display regressions join
parallel discovery automatically:
    python -X utf8 -m unittest discover -s tests -p test_defense_display.py -v
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui
Owner check: assign/release patrol and inspect the strength change, current
health/morale effects and the hover component explanation; check mobile layout.

## Bot audit traces, economy personalities and upgrades

Before enabling bots, restart player/admin servers and the bot runner with the
same save. New controller schema additions initialize at startup, preserve
existing bots, and default them to Balanced. Create new bots with Balanced,
Builder or Scavenger personality. Builder prioritizes useful infrastructure
upgrades; Scavenger sometimes chooses recovery before nonessential growth.
Safety, staffing, costs, utilities, storage, protection and timers stay identical.
Seeds plus step number and policy version are recorded for reproducible choices.
All profiles now consider affordable upgrades that relieve supply, storage or
housing constraints; essential staffing always takes precedence.

Bot decisions are no longer pruned automatically. Durable bot_traces record
step start, own observed resources/reservations/storage/rates/citizens/buildings/
jobs/site progress, chosen reason/parameters, action start, completion/rejection,
request ID and post-action own state. Credentials and private loot rolls/nonces
are excluded. Crashed in-flight actions can leave a start without an outcome;
transport errors explicitly have unknown outcome, not a guaranteed rejection.
Ordinary player request/game logs provide independent correlation.

Admin → Bots → Decision traces shows paginated records and JSON export (200
records/page; older records remain available). Existing controller pause and
read-only map inspection remain. Retained history can grow; backup the save for
long campaigns. Historical decisions before this update cannot gain missing
snapshots retroactively. Policies can change only by explicit code/rule edits,
not by bot decisions.

The admin page lists coverage honestly: these are still economy bots. Military
manufacturing, repairs, ration policies, trade/market, banking, diplomacy,
patrols/combat/capture/expulsion are not automated yet. Aggressive, trader and
defensive profiles should be introduced with those actual behaviors in later
increments. Start one or several economy profiles only after owner validation.

No bots, servers or tests were run by Codex. New audit tests join discovery:
    python -X utf8 -m unittest discover -s tests -p test_bot_audit.py -v
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui
Owner acceptance: create profiles in a disposable save, inspect observed/decided/
action/outcome traces and request IDs, test a rejected action, and export history.

## Military and combat bot behavior

Five profiles are now available: Balanced, Builder, Scavenger, Aggressive and
Defensive. Normal survival/staffing priorities come first. Profiles vary the
frequency of military investment and raids; Defensive never initiates attacks.
Military choices build compatible storage/factories and defensive posts/turrets,
assign factory staff/guards/patrols, queue affordable non-repeating single-unit
equipment batches, and start/staff paid building repairs. Drone servicing and
capture integration/expulsion remain deferred.

Offensive bots use unassigned integrated healthy home citizens, ready offensive
drones and operational stored missiles. They never send the Administrator or
production workers, keep six citizens home and obey protection, treaty blocks/
cooldowns, war-warning delay, attack allowances and season finalization. They
avoid a second in-flight raid on the same target. Targets come from a player
API containing only ordinary visible opponent IDs/names/protection, own war
state and own raid state; no opponent stocks, citizens or defensive hardware are
read. Objectives vary with the existing enabled options and available forces.
Bots can attack eligible human settlements as well as other bots.

Own observation traces now include military equipment/inventory and public
target eligibility; seed/personality/policy version military-v3 remain recorded.
HTTP form encoding supports multiple citizen/drone IDs, exactly like player
forms. Trade, market, banking and diplomatic treaty actions were not added.
War declaration is the existing conflict action, not treaty-management automation.

Restart player/admin servers and any bot runner with the same save commands.
Existing profiles retain their names and gain occasional military behavior;
Aggressive/Defensive are selectable for newly created bots. Normal newcomer
protection may delay attacks substantially; bots do not bypass it. No tests,
servers or bots were run by Codex. New regressions join automatic discovery:
    python -X utf8 -m unittest discover -s tests -p test_bot_combat.py -v
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui

The prior policy-version assertion now expects military-v3; its economy-upgrade
behavior check is unchanged. Owner acceptance: inspect factory/storage/staffing
decisions and finite production batches, then normal declarations, waiting and
raid requests in a disposable multiplayer save. Verify target privacy, leave-six
limits, protection and request IDs. Combat balance remains under observation.

## Material flow in the header and map action inspector

Scrap, Metal and Electronics now show net/hour plus the active scavenging
contribution. Net is the current plan before storage limits; scavenging is gross
yield, not guaranteed retained stock. Paused net rates are forecasts, with no
current scavenging yield. Labels update in place and remain compact on mobile.

Click a built structure, derelict or destroyed-building ruin in Place/inspect
mode to open a compact action inspector. It moves the existing management node
into the inspector and restores it on close; no duplicate forms or element IDs
are created. Worker/scavenger assignment, releases, upgrades, repairs, project
cancellation and demolition remain the existing authenticated forms and guards.
Existing disabled controls show unavailable actions. Demolition/cancellation
requires the existing confirmation and an additional explicit prompt.
Close with the button or Escape. Clicking another structure switches the
inspector. Pan mode remains separate. No rules or transaction routes changed.

Restart only the player server with the same save, then refresh the browser.
Codex ran no tests, browsers or gameplay actions. New selector regressions are
automatically included by --include-ui:
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui

Owner acceptance: scavenge each material, inspect displayed rates against the
scavenging overview, and test full/paused storage. Click buildings and derelicts,
assign/release workers, open/close/switch inspectors, check keyboard focus and
small screens, and cancel a demolition prompt without changing a building.
Verify job progress still updates while its original node is in the inspector.

## Map attention filters and bot username help

Map filters highlight Unstaffed, Stalled work or Damaged structures while dimming
other footprints rather than hiding occupied land. All restores the normal map.
Matches update live and remain clickable. Passive buildings are not falsely
unstaffed; paused seasons are not falsely stalled; construction zero HP is not
automatically counted as damage. Ruined structures count as damaged.

Bot creation now suggests an unused bot_N username and Bot N settlement name,
checks names against existing accounts/reservations, and shows the exact format.
Usernames need 3–24 letters/numbers/underscores and start with a letter; spaces
and hyphens belong in the settlement name instead. Uppercase letters are now
accepted in the browser and normalized lowercase by the existing account service.

Restart both servers with their same database commands and refresh. Codex ran no
tests, servers or bots. New filter and name tests are automatically discovered:
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui
Owner check: switch each map filter, confirm nonmatching occupied land is still
visible, inspect paused/active projects and create a second bot using its suggested
username. Suggestions are convenience only; server uniqueness checks still apply.


## Daily market reserve (owner validation pending)
Each settlement can buy 30 Food, 30 Water, 20 Scrap, 10 Metal and 5 Electronics
per UTC calendar day, for 2/2/3/6/15 Credits per unit respectively. Limits reset
at UTC midnight, never accumulate, and are independent of player listings.
Normal available-Credit, storage, suspension and season restrictions apply.
Payments go to the Bank; there is no seller fee or treaty discount. Quantities
and prices are prototype balance settings in config/market_reserve.json. Set
enabled to false to disable; restart the game after editing configuration.
Purchase history persists in market_reserve_purchases, game events and paired
Credit ledger entries; safe request logging includes reserve_buy failures.
Restart the game with its existing command/database; do not reset the save.
The purchase table is created transactionally on first successful purchase.
Tests are automatically discovered by run_tests_parallel.py. Codex did not run
tests or servers. Owner command:
    python -X utf8 run_tests_parallel.py --workers 2


## Build and upgrade market shortcuts (owner validation pending)
Missing-material messages for upgrades (including Town Hall) and unavailable
buildings link directly to the Public Market. Build links update with live
spendable stock; unlock-only restrictions do not suggest buying materials.
The link navigates only; buying and building remain separate confirmed actions.
Restart the game using the same save and refresh the browser. New regression
tests are automatically discovered by the parallel runner. Codex ran no tests.


## Pooled market replaces listings (owner validation pending)
Public Market now shares season-wide Food/Water/Scrap/Metal/Electronics inventory.
Sales immediately remove unreserved goods and pay Credits from the Bank; purchases
consume shared stock. Stock starts empty, never refills automatically, and does not
carry between seasons. Personal daily reserves remain independent and unchanged.
Fixed buy prices: 2/2/3/6/15; gross sell prices: 1/1/2/4/10 Credits per unit.
Seller fees retain the 8% base and Trading Post reduction, 2% minimum, rounded up.
No trade-agreement reduction applies because there is no bilateral market sale.
Direct trades remain fee-free and trade treaties still exist. One-unit Food/Water
sales have zero net proceeds after rounding and are rejected; sell a larger batch.
Sales use the existing paired Bank ledger, which permits a negative reserve; Bank health continues to reflect that balance.
Configuration: config/market_pool.json and config/market_reserve.json. Selling
prices must stay below both purchase prices to prevent profitable resale loops.
Restart player and admin servers with the SAME database. Startup cancels old open
listings and releases their reservations without selling, paying, or adding goods
to shared stock. Old listing transaction history and daily reserve usage persist.
Stop old processes before restart; old code must not keep writing listings.
Pooled tables and the reservation migration are additive/idempotent. No live save
was modified by Codex. Panel revision includes shared stock and daily rollover.
Market logs contain market_pool_trade, market_listing_migrated and paired Credit
ledger rows; failed requests include the sell action. Admin diagnostics check stock.
Listing-only social tests were rewritten for the explicitly approved rule change;
atomicity, reservation safety, discounts, storage, time guards and concurrent
purchases remain covered. New migration/season/reserve integration tests join
automatic parallel discovery. Codex ran no tests, servers, bots or playtests.
Owner validation:
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui


## Derelict map inspection: salvage preview (owner validation pending)
Clicking a derelict opens the existing inspector with possible Food, Water,
Scrap, Metal and Electronics yields. The estimate uses public type ranges,
remaining job progress and current material-salvage bonuses; it never reads the
private random roll. Zero-yield resources are omitted. Active previews update
with normal value polling, and cleared sites show no salvage remaining.
Actual quantities vary, bonuses can change, and storage overflow is discarded.
Restart the game with the same database and refresh. Regression tests are
automatically discovered by run_tests_parallel.py; Codex did not run tests.


## Bots use the shared market and personal reserve (owner validation pending)
Policy market-v4 observes public stock/prices and its own reserve allowance via
the normal player API, and submits ordinary /market requests with normal CSRF.
It buys deficit Food/Water below a two-hour buffer, aiming for six hours (minimum
10 units); chooses the cheaper available stock and uses shared inventory on ties.
It buys missing materials for eligible economy builds/upgrades, retaining 50
Credits for non-emergency purchases and checking current material capacity.
Surplus sales happen after useful staffing/building decisions, with positive net
production/recovery near 85% capacity, batches up to 25, and working stock reserves.
Food/Water retain up to six hours or at least half capacity (at most 80% capacity).
Materials retain at least 80 Scrap, 40 Metal and 10 Electronics, or six hours of
converter consumption. Unreserved stock only; active manufacturing blocks material
sales. These are conservative bot heuristics, not player-rule changes.
Private trade, banking and diplomatic actions are still deferred for bots.
Traces include the observed market, chosen source/quantity/reason, HTTP outcomes
and existing before/after snapshots. Races/exhausted stock fail normally and are
re-evaluated on the next turn, without privileged retry or special stock.
Restart the game and bot runner with the same database/commands. Restart admin
to update behavior-coverage text. No bot reset or save reset is required.
New bot-market regression tests are automatically discovered by the parallel
runner. Codex did not run tests, bots or servers.


## Optional tips and full-storage markers (owner validation pending)
The resource bar marks Food/Water Full individually; Scrap/Metal/Electronics
show Full together when their shared storage fills. Markers work even when rates
are zero or negative; Credits have no storage marker. Hover/focus the marker for
used/capacity and click to review construction/storage. Normal polling updates it.
Gameplay tips are a small non-modal card: first after 30 seconds, at least ten
minutes apart, at most three automatically per UTC day in this browser/settlement.
They do not take focus or appear over form entry, map inspection or critical
resource warnings. Close, Next tip, and automatic-tip preference controls are
available; Gameplay tips in the interaction navigation opens them manually.
Preferences persist in browser local storage. Blocking storage limits persistence
to this page; no gameplay state or save is changed.
Restart the game using the same database and refresh. Python tests and optional
Node UI tests are automatically discovered by run_tests_parallel.py --include-ui.
Codex ran no tests or browser playtests.


## Owner report: 712 tests, one failure and seven errors
Reviewed the saved parallel-20261011T233752077976Z output without rerunning it.
All seven errors share the same legacy rendering cause: the defense header called
combat.maximum_hp on V1 configuration, which has no simulation section. Several
HTTP tests surfaced the same rendering exception as RemoteDisconnected. The HP
helper now uses the existing V2 simulation fallback for legacy configurations;
current configured HP progression is unchanged. No save upgrade is performed.
The admin failure expected correction controls on /admin, now the Season page.
Its test now visits /controls?section=corrections and retains all correction,
stale-value, invalid-input, resume and preserved-save assertions.
Additional legacy rendering/HP regressions join automatic parallel discovery.
Corrections have been installed but not validated by a test run; Codex did not
run tests or servers. Owner command:
    python -X utf8 run_tests_parallel.py --workers 2 --include-ui


## Bot runner database contention fix (owner validation pending)
A reported runner crash came from trace insertion during a SQLite write lock,
followed by another trace insertion in its error handler. Audit wrappers now
fall back to logs/bot-runner-errors.jsonl (UTC timestamps, 5 MB plus 3 rotations)
when database logging fails. Admin Logs shows the latest bounded current-file
entries for this save. No cookies, passwords or session-token hashes are logged.
Startup/claim lock contention waits three seconds and checks again. Step and
session-cleanup lock failures do not kill the runner. A failed decision-record
write is retained in the fallback file; its existing two-minute claim lease
expires normally if it cannot be released. Expiring sessions may remain until
normal session expiration if cleanup is blocked. Other database errors at claim
or startup stop with a clear message instead of being mislabelled contention.
HTTP timeout outcomes remain unknown: no automatic POST or whole-step replay.
Each later decision refreshes ordinary player state and is re-evaluated normally.
A server disconnect still needs the player server running at the configured URL.
Restart the bot runner and admin suite with the same commands/save. No reset is
required. Use only one runner per save. New regressions join automatic parallel
discovery. Codex did not run bots, servers or tests and did not alter the save.


## Explore the Wastes and resource capacities (owner validation pending)
Resource headers now show / capacity; material labels say shared. Credits have no
cap. In Military, citizen-only expeditions spend packed whole Food/Water upfront.
Full normal consumption is snapshotted per explorer; packed supply must cover the
15-minute return, with up to 24 hours gathering. Scarcer supply limits time.
Each citizen gathers 2 Scrap/0.5 Metal/0.1 Electronics per hour, +10% per level
above 1 (launch level); rates/timing are editable in config/expeditions.json.
Only living integrated free citizens at home can launch; keep at least one home.
Away citizens cannot work, defend, join raids or consume home supplies. Recall
stops gathering immediately and starts the 15-minute return; no gathering in
transit. Packed supplies are consumed in transit; unused provisions return.
Arrival keeps only what current storage fits; overflow is explicitly reported.
No expedition injuries/death or XP progression in this first prototype.
Shared pause/suspension shifts expedition clocks. Launches close in finalization;
season end settles remaining expeditions before the final snapshot.
Gameplay actions are normal authenticated/CSRF-checked requests and logged.
Restart the game and admin with the same save; no reset. New tables initialize
additively on account startup. Bot expedition decisions are not automated yet.
Codex did not run tests/servers or modify live save data. New tests automatically
join run_tests_parallel.py; owner validation remains required.


## Personality-driven bot expeditions (owner validation pending)
Policy expeditions-v5 adds normal citizen-only launches and recalls. Scavenger
bots favor up to two citizens / six hours; Balanced one / three hours; Builder
one / two hours; Aggressive one / 1.5 hours; Defensive one / one hour. Seeded
launch chances per eligible decision are 75/30/20/15/10 percent respectively.
Aggressive/Defensive retain six citizens at home; other profiles retain 2–3,
plus at least one idle citizen. Administrators/production workers are never taken.
Existing stalled crew needs, production staffing and urgent purchases take
priority. Active projects or another away expedition prevent additional launches.
Bots keep six hours of home consumption (minimum 12 Food/Water), avoid deficit
launches and shorten provisions when projected material storage would fill.
They favor higher-level idle citizens, and recall for supply pressure, stalled
projects needing staff or a haul that reaches remaining material storage.
All launches/recalls use normal HTTP, costs, travel, storage and ownership rules.
Before/after traces include expedition provisions, deadlines, yields and outcome.
Restart the bot runner and admin with their existing commands/save; no reset.
New tests join automatic parallel discovery. Codex did not run tests or bots.


## Map build overlay (owner validation pending)
A small tools icon at the map's upper left opens Build on the map: the same
construction form and requirements are temporarily moved into a compact overlay,
with no duplicate IDs, CSRF tokens or alternate spending route. Choose a building,
rotate it, click empty land to preview, then Start construction to confirm.
Nearby site suggestions, material shortfalls, market links and utility warnings
retain existing behavior. Closing/Escape restores the controls below the map.
Clicking a structure switches back to its existing inspection controls.
Restart the game with its existing database command and refresh. No rules/save
were changed. New optional UI regressions join automatic --include-ui discovery.
Codex did not run tests or browser playtests.


## Owner market report parallel-20261012T010736033594Z
Corrected four reported failures without changing gameplay: the Flask integration
test now sells/buys fixed-price pooled goods, checks seller/buyer balances, shared
stock and balanced ledger rows, and rejects retired listing/cancellation forms.
Allowance-independence and midnight-rollover fixtures now leave enough shared
storage for their intended purchases. Limit rejections explicitly check the
daily-allowance message so unrelated storage errors cannot satisfy the tests.
Existing full-storage rejection tests remain unchanged. Codex did not run tests.
Owner command: python -X utf8 run_tests_parallel.py --workers 2


## Approved Garden Oxygen change (owner validation pending)
Current v13 Garden has no operating Oxygen requirement/demand; it adds 1 Oxygen
capacity per effective worker in a 3-tile radius alongside 6 Food/hour per worker.
Two operating slots, 35 Scrap, 15-minute base build time, 150 HP, 10 Food storage,
no electricity and no upgrades remain. Staff productivity and condition scale both
outputs. Outside-coverage construction/initial Garden staffing still requires the
existing exposure confirmation; no worker-safety exemption was added.
Source workbook and legacy profiles are unchanged. Existing v13 Gardens use the
new rule after server restart; no save migration/reset. Online guide/catalogue
and its manifest are updated; the old PDF is explicitly marked previous-edition.
Restart game/admin/bot runner so cached configuration reloads consistently.
New Garden regressions join automatic parallel discovery. Codex ran no tests.


## Consistent Food-building Oxygen rules (owner validation pending)
Current v13 Garden, all three Greenhouse levels and all three Hydroponics levels
produce 1 Oxygen capacity per effective worker in a 3-tile radius, without an
operating Oxygen requirement/demand. Existing Food output, costs, build/upgrade
times, staffing limits, unlocks, HP and storage are unchanged. Greenhouse and
Hydroponics still require their existing electricity: lost power stops both
Food and Oxygen output. Initial staffing/construction outside coverage still
requires the existing explicit citizen exposure confirmation. Specialist Oxygen
buildings are unchanged; original workbook and legacy profiles remain read-only.
Restart game, admin and bot runner to reload cached rules; no save reset needed.
Online guide/catalogue and manifest are updated. The PDF remains labelled as
previous-edition. New regressions join automatic discovery; Codex ran no tests.

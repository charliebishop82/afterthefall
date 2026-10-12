# Running the game and operator tools



Project folder: `C:\Users\charl\OneDrive\Desktop\multiplayer war game`.

The commands below are for PowerShell. Keep each server in its own terminal;

use another terminal for tests and management commands.



## Working together from Conda

**Owner instruction: Codex must not run any tests unless explicitly asked.**
This includes focused checks and the full suite. Codex still writes tests and
provides commands; checks that have not been run remain pending.




See [Development and validation handoff](COLLABORATION.md) for the agreed workflow.



Codex edits the code, documentation and regression tests, and runs tests only when explicitly requested.

You run the game/admin servers, manual playtests and the full test suite in your

Conda terminals. No application-code change or new test framework is needed.

Changes awaiting your full-suite result are ready for validation, not yet fully

validated. Each handoff should include the changed behavior, focused test result,

exact commands and a short playtest checklist. Share failures so they can be fixed.



After code or configuration edits, stop the affected server with Ctrl+C and start

it again to load the new code. Refreshing a page alone does not restart Python.

Pause an active season through the admin console first if downtime should not

count as game time. Use a different terminal for tests; tests use temporary saves

and can run while your local servers remain online.



If a server was started by Codex and its port is still occupied, ask Codex to stop

that specific server for the initial handoff. Starting another process on the same

port will not take it over. No running servers are stopped by these instructions.



## 1. Set up your dedicated Conda environment



Python 3.12 is the version used for this project's current validation.

You can choose a different environment name; `settlement-game` is an example.



```powershell

conda create --name settlement-game python=3.12 pip

conda activate settlement-game

Set-Location 'C:\Users\charl\OneDrive\Desktop\multiplayer war game'

python -m pip install -r requirements.txt

python -m pip check

python -c "import sys, sqlite3; print(sys.executable); print('SQLite:', sqlite3.sqlite_version)"

```



SQLite must be version 3.37 or newer for the database's STRICT tables.

Each time you open a new terminal, activate the environment and enter the

project folder again. If PowerShell does not recognize `conda activate`, use

Anaconda Prompt, or run `conda init powershell` and reopen PowerShell.



### Packages needed



Install the existing `requirements.txt` as a whole. It pins the versions currently

used by the project:



| Package | Version | Purpose |

| --- | --- | --- |

| Flask | 3.1.3 | Player application and independent admin application |

| waitress | 3.0.2 | Local web servers |

| Werkzeug | 3.1.9 | Flask HTTP utilities |

| Jinja2 | 3.1.6 | Flask template dependency |

| MarkupSafe | 3.0.4 | Template escaping dependency |

| itsdangerous | 2.2.0 | Flask dependency |

| click | 8.5.0 | Flask command dependency |

| blinker | 1.9.0 | Flask signaling dependency |



Flask and Waitress are the direct web dependencies; the other packages are

their dependencies. SQLite, password hashing, logging and the `unittest` test

runner come with Python. No separate database server or pytest installation is

needed. Reference Word/Excel documents are not required packages for running

the game. Ngrok is optional software for future public access, not a Python

dependency.



You do not need to activate the project's `.venv` when using Conda. The existing

PowerShell launchers use `.venv` by default; the direct `python` commands below

use your activated Conda environment instead.



## 2. Start the player game



```powershell

conda activate settlement-game

Set-Location 'C:\Users\charl\OneDrive\Desktop\multiplayer war game'

python -X utf8 serve_game.py --port 8767

```



Open http://127.0.0.1:8767/. This is the current multiplayer Flask application,

served by Waitress. Its default save is `database/playtest.db`. First startup

creates a fresh save if it does not exist; restarting keeps the existing save.

Do not delete it to restart the server.



Players register accounts and reserve settlement names while the lobby waits.

No settlement time runs until an administrator starts the group from the console.

Enrollment closes at launch. Closing a server alone does not pause an active

game: use the admin pause control when you want downtime excluded from gameplay.



## 3. Create your administrator account



Start the player game once so the playtest save exists. In another activated

terminal, from the project folder:



```powershell

python -X utf8 manage.py create-admin admin

```



This privately prompts for a password of 12–128 characters and confirmation.

It creates an administrator account without enrolling a player settlement.

If `admin` already exists as a regular account, grant that existing account the

role instead:



```powershell

python -X utf8 manage.py grant-admin admin

```



Registration never grants administrator rights automatically. Neither command

sets a default password. Run management commands only on the host computer.



## 4. Start the separate admin suite



In its own activated terminal:



```powershell

python -X utf8 admin_suite.py --port 8768

```



Open http://127.0.0.1:8768/ and log in with the administrator account. This is

an independent process with its own login cookie. It can run with the player

server online or stopped, and reads/writes the same `database/playtest.db`.



- Controls: shared lobby launch, season pause/resume, account suspension,

  password resets, announcements, moderation and audited value corrections.

- Diagnostics: read-only integrity, foreign-key and targeted consistency checks.

- Logs: recent game events and operator service output. Before/after audit history

  appears under Controls; older audit rows remain in the database.



Corrections require paused time or suspension of the affected settlement and a

reason. See [Admin operations](docs/admin-operations.md) for supported corrections

and limits. Operator file logs are in `logs/admin-suite.log`, with three rotated

older files. Keep this console local when exposing the player game publicly.



## 5. Stop and restart



Press **Ctrl+C** in the relevant server terminal. Stop player and admin processes

independently. Restart them with the same commands and database paths.



If a port is already occupied, use the existing server or stop its terminal before

launching another copy. The usual addresses are:



| Tool | Script | Port | Default save |

| --- | --- | --- | --- |

| Current player game | `serve_game.py` | 8767 | `database/playtest.db` |

| Independent operator suite | `admin_suite.py` | 8768 | `database/playtest.db` |

| Original single-settlement sandbox | `app.py` | 8765 | `database/prototype.db` |

| Legacy account game | `accounts_app.py` | 8767 | `database/accounts.db` |



## 6. Run regression tests



From an activated environment and the project folder:



```powershell

python -X utf8 run_tests.py

```



The runner also prints the ten slowest tests and writes `test-timings.json` in

the project folder, including per-test results and totals by module. Use

`python -X utf8 run_tests.py --slowest 20` to show more timing entries.



The full suite uses temporary saves, not player databases. It can take around

30 minutes or longer depending on the machine. Success ends with `OK`; inspect

any failure before treating a change as validated. See [Testing](docs/testing.md).



All automated test modules are in `tests/` inside this project folder. Keep the

`sources/` reference documents with the project: some tests verify configuration

against the current workbook. They read it without changing it. `run_tests.py`

is the full-suite entry point; `test-timings.json` records the results. The current

suite is expected to have 622 tests across 39 test modules; these counts will grow.



To keep live progress and a shareable log in PowerShell:



```powershell

python -X utf8 run_tests.py 2>&1 | Tee-Object -FilePath test-results.log

$LASTEXITCODE

```



A successful run ends with `OK` and exit code `0`. If it fails, send

`test-results.log` (or the complete failing traceback) and `test-timings.json`,

along with the command used and your Python version. Keep passwords and live

player database files out of test reports. Do not reset your playtest save to

repair a test failure: tests use their own temporary saves.



For a focused operator check during development:



```powershell

python -X utf8 -m unittest discover -s tests -p test_admin_suite.py -v

```



A focused run does not replace the full regression suite for a feature release.



## 7. Back up and restore



Create a consistent SQLite backup, including while the game is online:



```powershell

python -X utf8 manage.py backup

```



The command prints its unique destination under `database/backups/`. To select

a different new output file, use `manage.py backup --output PATH`.



To restore, first stop **all applications using the target save**, including the

player game and admin console. Replace the example backup name with the actual

file you want to restore:



```powershell

python -X utf8 manage.py restore 'database/backups/YOUR_BACKUP.db' --server-stopped

```



Restore makes a recovery backup of the previous save and revokes restored login

sessions. It rolls back gameplay to the backup's state. Restart both applications

afterward. `--server-stopped` is your confirmation; it does not stop servers for you.



## 8. Select a different save



Use the same path for the player app, console and management tools:



```powershell

python -X utf8 serve_game.py --database database/playtest-next.db --port 8767

python -X utf8 admin_suite.py --database database/playtest-next.db --port 8768

python -X utf8 manage.py --database database/playtest-next.db create-admin admin

python -X utf8 manage.py --database database/playtest-next.db backup

```



These are separate commands/terminals, not one batch to leave running.

Start the player app first to initialize a new playtest save. A fresh playtest

must use a fresh path; do not point it at an old sandbox or legacy account save.



## 9. Other scripts and existing launchers



```powershell

# Original sandbox, using its separate saved settlement:

python -X utf8 app.py --port 8765



# Legacy account server; choose another port if the current game uses 8767:

python -X utf8 accounts_app.py --port 8769



# Inspect command options without launching a server or changing saves:

python serve_game.py --help

python admin_suite.py --help

python manage.py --help

python database/create_database.py --help

```



`database/create_database.py` creates the base V1 schema; normal player-server

startup handles the additional playtest/account setup. You normally do not need

to run the schema script manually. It is not a reset or migration command.



`./start_game.ps1` and `./start_admin.ps1` remain convenient launchers for the

existing `.venv`. For Conda, use the direct commands in this guide. The game

launcher also accepts an explicit interpreter:



```powershell

./start_game.ps1 -Python (Get-Command python).Source

```



## 10. Future public playtests



The current commands bind locally. Public hosting setup is described separately

in [Flask playtest setup](docs/flask-playtest.md), including the existing ngrok

configuration example. Publish only the player service; leave the operator suite

on its local address. Do not enable Flask debug mode for public playtests.





## 11. Read-only building and economy checks



```powershell

python audit_buildings.py

# Optional: write detailed catalogue evidence outside the read-only sources folder.

python audit_buildings.py --output building-audit.json

```



This uses Python's standard library. It checks configured levels, staffing,

renewable material producers, hardware dependencies and Town Hall storage paths;

it does not alter saves or source documents. See

[the building/economy review](docs/building-economy-review-2026-10-11.md) for the

approved renewable Scrap rule, test evidence and remaining playtest work.

Restart the game and admin services after changing configuration files.



## Current features and outstanding acceptance work



See [the complete game review](docs/current-game-review-2026-10-11.md) for current rules, tested systems, missing V1 features and suggested increments. The player Advisor uses local rules and saved reports; operator Logs support exact filters, older pages and bounded JSON export. Neither feature adds a runtime package. Balance configuration editing, final map/HUD art and complete seasons are not yet implemented.



## Player guide



Players can open http://127.0.0.1:8767/help before creating an account or from

the in-game Help link. Download the printable handbook at `/help.pdf`; the

standalone files are `docs/player-guide.html` and `docs/player-guide.pdf`.

No extra packages are needed to serve or read them.



After changing gameplay or configuration, review the narrative in

`tools/build_player_guide.py` and regenerate both editions together:



```powershell

python -m pip install reportlab

python tools/build_player_guide.py

python -m unittest discover -s tests -p test_player_guide.py

```



ReportLab is an optional documentation-building dependency, not a game-server

requirement. The builder derives the building and hardware tables from the

current prototype and expansion configurations; narrative rule changes still

need an editorial review. `docs/player-guide-manifest.json` records the edition

and configuration fingerprints.


## Player action and error history

After restarting the player server, `serve_game.py` automatically writes
`logs/player-actions.jsonl`. No additional package or database change is needed.
Your existing `--database` argument still selects the save; each log record names
that database so different playtests can be distinguished.

The log records every HTTP request, including page visits, automatic resource
refreshes, login/account actions and successful or rejected gameplay actions.
Start/finish records share a request ID. Completion records include UTC timestamps,
account ID when available, known action, safe numeric targets/amounts, response
status, duration, action timestamp and the saved settlement clock observed at
completion. Errors include their type and source-file/function/line locations;
clock rejection has the explicit `clock_before_saved_state` code. `X-Request-ID`
in the response headers connects a browser error with the matching log records.
A started request without a finish record can indicate interruption or a crash.

Passwords, cookies, session/CSRF tokens, query strings, unknown paths, free-text
messages, settlement names and arbitrary exception messages are excluded. Existing
SQLite `game_events` remain the authoritative record of successful simulation
changes; the request log supplements them with attempts and failures. A completed
HTTP request alone is not a complete before/after audit of every database row.

Logs rotate at 10 MB, keeping five older files (`.1` through `.5`). This is bounded
recent history, not a permanent archive. Copy relevant logs before older history
rotates away. Keep log files on the host; they are not published by the game.
Use `--log-file PATH` to select a different log file for a playtest.

To watch from a separate PowerShell window in the project folder:

```powershell
Get-Content 'logs/player-actions.jsonl' -Tail 20 -Wait
```

From Anaconda Prompt, use:

```bat
powershell -NoProfile -Command "Get-Content 'logs/player-actions.jsonl' -Tail 20 -Wait"
```

Press Ctrl+C to stop watching. When reporting a problem, provide the approximate
time, action and relevant start/finish records, or the request ID. The file begins
collecting after the updated player server is restarted; earlier rejected player
requests cannot be reconstructed from this new log.

## Read player logs in the admin suite

After code changes, press Ctrl+C in each affected server window and run its original
command again. Keep the same database path; restarting does not reset the save.
Activate the environment in both windows first.

Player window:
    python -X utf8 serve_game.py --database database/playtest-fresh-01.db --port 8767

Admin window:
    python -X utf8 admin_suite.py --database database/playtest-fresh-01.db --port 8768

In the admin suite, open Logs → Player requests and errors (or /player-logs).
Filter by account ID, request ID or errors only, choose current/older files, or
download matching JSON. Reload the page for new entries. This read-only view
shows up to 100 matches from the last 256 KB of one file, for the console's save.
Invalid or incomplete lines are skipped. It complements game events and correction
audit records; it does not fix the reported clock race.

If the player server uses --log-file PATH, launch the console with
--player-log-file PATH pointing to that same file. No extra packages are needed.
The game continues to count elapsed time while stopped unless paused through the
admin controls beforehand.

## Focused player interface

Restart only the player server with its existing database command to load this
interface update. Menu views separate Overview, Build & Buildings, Citizens,
Economy & Trade, Military, and Diplomacy & Messages. Supplies and urgent alerts
stay visible. The selected view is remembered in the browser tab after actions
and refreshes. Map links open the view containing the selected building or ruin.
Without JavaScript, the original full page remains available.

Explanations and the building catalogue use closed, keyboard-accessible info
blocks. On the Build view, the map and coordinate inputs still work. Selecting
a building type or orientation suggests the nearest empty full footprint beside
the Town Hall. Find nearby empty site repeats the suggestion. Red previews mean
overlap or out-of-bounds placement. Empty space is only a suggestion: utility
coverage, materials, workers and unlocks still use the existing game rules.

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

## Sticky resources

The live resource bar stays at the top of the viewport while scrolling the
settlement, across all menu views. It uses one compact row on wide screens and
two rows on small screens. Small-screen explanatory subtitles are hidden to
leave more space for the game; labels and current amounts remain visible.
This is a CSS-only change: Ctrl+F5 loads it without restarting either server.
No tests were run. Owner visual check: scroll through each view and check the
resource bar remains visible, updates live and does not obscure map controls.

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

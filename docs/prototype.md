> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# Prototype increment 1: a saved settlement

> This guide records its original increment. Later implemented features and current limitations are listed in [the consistency review](review.md).

Historical notes for the first increment. For current resource simulation and
clock/staffing controls, see `resources.md`.

## Run

From this project directory, run `python app.py`, then open
http://127.0.0.1:8765 in your browser. Create your settlement using the form.
Stop with Ctrl+C. Run the same command to return to the same saved settlement.

On this computer:

```powershell
& 'C:/Users/charl/miniconda3/python.exe' 'C:/Users/charl/OneDrive/Desktop/multiplayer war game/app.py'
```

The default save is `database/prototype.db` beside the application, regardless of
the working directory. The original `database/game.db` remains unchanged. For a
separate test save use `python app.py --database database/another-prototype.db`.
Do not delete or overwrite a save to upgrade it. Unknown schema/configuration
versions and unrelated game data are rejected. There are no schema changes here.

## Available now

- Create one named local settlement, atomically and only once.
- See a 40×40 map with a 3×3 Level-1 Town Hall near the center.
- See six distinct Level-1 citizens and the saved supplies.
- Inspect the Town Hall and citizen roster using page links.
- Close/reopen the browser or restart the server without losing the settlement.

The first citizen holds the Town Hall Administrator assignment; the other five
are unassigned. All initial citizens tie on level, XP, and arrival time, so the
first citizen ID breaks that initial tie. Names are fixed demonstration content.
The heading “After the Fall” is a prototype label, not a final game-title decision.

## Deliberately inactive

The prototype season is paused. There is no simulation, elapsed-time catch-up,
production, consumption, construction, scavenging, map derelict generation,
citizen progression, multiplayer login, trade, or combat. The empty land is a
placeholder for later generation. Closing the app never consumes supplies.

This standard-library server binds only to 127.0.0.1. It is a local development
prototype, not a public multiplayer server. No login is implemented; the internal
local account has a disabled password marker and is inactive. Forms have a
per-server token, origin checks, bounded bodies, and escaped output. Only explicit
page/style routes are served; database/source files are not exposed.

## Configuration and audit

`config/prototype_v1.json` is a small, versioned subset of the current workbook.
Its source notes identify the sheet/setting for each group. Starting resources
are 120 Food, 120 Water, 180 Scrap, 40 Metal, 10 Electronics, and 500 Credits.
Town Hall capacity is 10 citizens, 150 Food, 150 Water, and 250 shared materials.
Citizen starting HP is 100 and morale is 60. Do not change this version in place
once saves use it; add a new version plus explicit save compatibility handling.

Initialization records citizen origin/membership/level history, an initial game
event, and matching Bank/settlement ledger entries for starting Credits. The Bank
starts at -500 for this one-player fixture; a configured real-season reserve is
deferred with financial gameplay. Nothing grants repeated starting supplies on
reload, duplicate form submission, or restart.

## Verification and next increment

Run `python run_tests.py`. Tests cover the original schema plus workbook-backed
configuration values, initialization, concurrent duplicate requests, complete
transaction rollback, persisted changes across reopening, invalid saves, HTTP
forms, escaping, and the page flow across an actual server restart. Test state
is isolated in temporary directories.

Next: resource production/consumption and worker assignment with a controlled
clock for tests. Keep unresolved utility/storage mechanics deferred until needed.

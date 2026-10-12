# Post-Apocalyptic Multiplayer Settlement Game

Current multiplayer entry point: Flask with Waitress, with accounts, administrator
controls in an independent operator suite, and a waiting lobby for a fresh synchronized playtest. Existing civilian,
military, citizen, trading, combat, diplomacy, communication and Bank gameplay is
available at launch. Complete season endings remain deferred.

See [Running the game and operator tools](RUNNING_THE_GAME.md) for the current commands and Conda packages. The rules-based Advisor and current feature coverage are documented in [the full review](docs/current-game-review-2026-10-11.md).

See [Flask playtest setup](docs/flask-playtest.md) for local startup, administrator
access, the shared start, backups and optional ngrok hosting. Run
`./.venv/Scripts/python.exe serve_game.py` and open http://127.0.0.1:8767.
Install the pinned dependencies from `requirements.txt` into `.venv` first.

See [Admin operations](docs/admin-operations.md) for season pause/resume, frozen
player suspension, and audited corrections to resources, HP, morale, attacks and debt.

The new save is `database/playtest.db`; existing `accounts.db` and `prototype.db`
are preserved. The legacy account server (`python accounts_app.py`) and original
single-settlement sandbox below still use their separate saves. The legacy
servers need no external Python packages.

See [the consistency review](docs/current-game-review-2026-10-11.md) for current coverage, corrected defects,
approved interpretations and deferred systems.

## Beginner player guide

Open `/help` from the login page or the game navigation. The self-contained
[HTML handbook](docs/player-guide.html) and [printable PDF](docs/player-guide.pdf)
cover the current prototype, a worked opening, flow diagrams, and every building
and upgrade. The guide is public and does not advance the game clock.

## Legacy single-settlement sandbox

Run `python app.py` and open http://127.0.0.1:8765. On this computer:

```powershell
& 'C:/Users/charl/miniconda3/python.exe' 'C:/Users/charl/OneDrive/Desktop/multiplayer war game/app.py'
```

Create a named settlement. It saves automatically to `database/prototype.db`.
Restarting the app or reloading the page preserves it. Time starts paused. Use Start time / Pause time to control production and consumption.
Choose your Town Hall Administrator and inspect hourly rates. Enable the successive
prototype features using the settlement controls; account settlements start with
the existing civilian features enabled.
See `docs/resources.md` for the current scope and `docs/prototype.md` for initial startup details.

## Source authority

The original documents remain unchanged in the project's `sources/`:

- Gameplay: `Multiplayer_Post_Apocalyptic_Game_GDD_v0.2(1).docx`.
- Persistence: `Multiplayer_Post_Apocalyptic_Game_Database_Design_v0.1(1).docx`.
- Balance/content: `Post_Apocalyptic_Game_V1_Building_Settings(1).xlsx`.

GDD v0.1 is superseded by v0.2. When new source versions arrive, use the most
current version. The `(1)` download suffix is not a document version.

## Create a database

From this project directory:

```console
python database/create_database.py
python database/create_database.py --path database/test.db
```

The default is always `database/game.db` beside the script, independent of the
terminal's current folder. A supplied relative path is relative to the terminal.
The creator refuses **every existing destination**, including empty files. It
does not reset data, change existing tables, create accounts, or seed a season.
Choose a new path for another empty database. Future upgrades use migrations.

For this computer, the installed Python used for verification is:

```powershell
& 'C:/Users/charl/miniconda3/python.exe' database/create_database.py --path database/test.db
& 'C:/Users/charl/miniconda3/python.exe' run_tests.py
```

## Verify

```console
python run_tests.py
```

Tests create temporary databases and never edit `database/game.db`. Every new feature must add tests, and the full existing suite must pass before an increment is complete. See `docs/testing.md`.

## Structure

```text
database/             Schema creator, connection helper, local game.db
  migrations/         Future explicit versioned upgrades
game/                 Simulation and transactional action services
config/               Immutable/versioned balance configuration
static/               Browser styles and scripts
templates/            Browser pages
docs/                 Implementation decisions and source discrepancies
tests/                Database, gameplay, interaction and HTTP checks
```

Use `database.create_database.connect_database()` for every game connection:
SQLite foreign-key enforcement is connection-specific. A connection context
commits or rolls back a transaction; `contextlib.closing` closes the connection.
Keep attacks, transfers, captures, and trades within one transaction.

The two entry points are `accounts_app.py` for account-based play and `app.py` for
the original sandbox. They use separate saves.

## Supply consequences and military production

Use **Enable supply consequences** for rations, shortage grace periods and health
loss while production continues. Use **Enable military production** to construct
factories and compatible storage, then queue drone, missile and interceptor batches.
See [Supply guide](docs/needs.md) and [Manufacturing guide](docs/manufacturing.md).
Basic drone deployment/combat now works after enabling support and defense; see docs/drones.md.
See `docs/database_decisions.md` for the boundary between schema and game logic.

## Food and construction

Place Gardens, assign builders and Food workers, and manage upgrades from the settlement page. Town Hall levels 2 and 3 unlock Greenhouses and Hydroponics. Scavenging and trading supply materials for later upgrades. See [Food guide](docs/food.md) for controls, source rules, and current limitations.

## Civilian economy

Enable civilian production on the settlement page for the complete Food/Water, utility, converter, and storage catalog and its workbook upgrade levels. Scavenge nearby derelicts for materials, expand utility coverage, and increase shared storage before larger upgrades. See [Production guide](docs/production.md) for the opening loop and current scope.

## Housing and survivors

Enable housing and survivors to add five independently buildable housing types
and rare citizen discoveries during scavenging. Housing is allocated automatically
and rescued citizens can immediately work. See [Housing guide](docs/housing.md).

## Citizen recovery

Enable citizen recovery to activate natural healing with supplies and safe
housing, plus current housing morale modifiers and powered comfort. The roster
shows effective morale, and the recovery panel explains each citizen's health
status. See [Recovery guide](docs/recovery.md) for rules and remaining limits.

## Citizen progression

Enable citizen progression for work XP and automatic leveling up to level 10.
The citizen roster shows cumulative XP. See docs/progression.md for rates and rules.


## Building repairs

Enable building repairs to assign crews to damaged permanent buildings and activate slow staffed Town Hall regeneration. Production continues while repairs restore HP. See docs/repairs.md for prototype costs and controls.


## Account-based local multiplayer

Run python accounts_app.py and open http://127.0.0.1:8767 for registration, login/logout and separate settlements in a shared season. Uses database/accounts.db; your local database/prototype.db remains separate. See docs/accounts.md for controls and scope.


## Private player trading

Account settlements can propose, accept, reject and cancel direct trades through the Player trading panel. Offered resources are reserved, exchanges are atomic and fee-free, and pending offers expire after 24 hours. Trade supplies can resume the prototype shortage freeze. See [Trading guide](docs/trading.md). Basic citizen raids are also available in account mode; see docs/combat.md.

## Basic citizen raids

Account mode now includes war declarations, a one-hour warning, citizen resource raids, protection and home-population checks, three daily attack allowances, injuries, loot and private battle reports. Rescue citizens beyond the initial six before deploying raiders. See [Combat guide](docs/combat.md) for approved prototype rules and deferred features.

## Support, guards and drone raids

Choose **Enable support and defense** to add Clinic/Medical Center treatment,
Salvage Depot bonuses, current Community Center morale, Engineering Workshop
construction/repair bonuses, Trading Posts and Guard Posts. Guard and patrol
assignments reserve citizens; map radii and readiness counts explain defense.
Account raids can now send offensive drones alone or with citizens. Air/ground
Defense Drones respond automatically, and survivors retain damage.
See [Support guide](docs/support.md) and [Drone combat guide](docs/drones.md).
Trading Post market-fee benefits apply to public market sales in account mode. Missiles and structural damage are available through the structural-combat increment below. Existing saves require explicit feature activation.

## Drone maintenance and building management

Choose **Enable maintenance and building management** for paid drone servicing,
manual/automatic Repair Drone orders, construction/upgrade cancellation and
voluntary demolition with workbook material recovery. Existing saves and prior
configurations are retained. See [Maintenance guide](docs/maintenance.md).

## Structural combat, destruction and citizen consequences

Choose **Enable structural combat and recovery** for finite missiles/interceptors,
local Automated/Anti-Air Turrets, infrastructure raids, building and occupant damage,
chain explosions, ruin salvage/clearing and rebuilding protection.
Choose **Enable citizen consequences** for Oxygen warnings and evacuation,
homelessness health loss, unemployment morale, births, desertion and expulsion.
Existing saves opt in explicitly; old elapsed time is preserved under its earlier rules.
See [Structural combat guide](docs/structural.md) and [Citizen guide](docs/citizens.md).

## Market, diplomacy and communication

Account mode now includes public market listings and partial purchases, Peace/Non-aggression/Trade Agreements, private mail with read/archive status, a moderated season board, public news and notifications. See [Player interaction guide](docs/social.md). Existing direct trades and war declarations remain available.


## Allied defense, capture, scores and Bank

In account mode, choose **Enable expansion for this season** in the Bank section
to add direct allied hardware defense, population and Credit raids, Vaults, public
season rankings, loans, investments and audited liquidation. The new rules start
at activation and preserve earlier progress. See [Expansion guide](docs/expansion.md)
for workbook settings and the approved prototype interpretations. Complete season
awards and new-season creation remain a later increment.

## Administration and local-network hosting

Use the protected admin dashboard for player access, password resets, announcements,
board moderation and audit history. Explicit local commands grant admin access and
back up or restore account saves. The launcher defaults to localhost and supports
configured trusted LAN addresses. See [Admin and hosting guide](docs/admin-hosting.md).


## Independent operator suite

Run `./start_admin.ps1` separately and open http://127.0.0.1:8768/. The player
application no longer accepts operator actions or starts the shared lobby. Create
an operator with `./.venv/Scripts/python.exe manage.py create-admin admin`, which
prompts privately for a password; an existing account can instead be explicitly
granted the role with `manage.py grant-admin admin`. The console uses the same
save as the player app, with its own login cookie and no settlement requirement.
See [Admin operations](docs/admin-operations.md) for corrections, diagnostics and logs.
Keep the operator console local when publishing the player app. Stop both apps
before restoring a backup.

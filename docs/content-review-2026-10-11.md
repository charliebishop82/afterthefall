> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# Game content and rules review — 11 October 2026

## Assessment

The prototype has most of the requested gameplay systems. The seven confirmed
inconsistencies below are corrected, with 578 regression tests passing, including
21 new checks. The original evidence remains below as
a record of the audit. Feature gaps and source conflicts remain separate follow-up
work; this does not certify balance or a complete V1 experience.

See [the correction notes](corrections-2026-10-11.md) for the resulting behavior.

This review compares the current Flask shared-start playtest, its game services,
configuration, regression tests and rendered HTML against the latest local sources
and the user's approved interpretations. Older opt-in sandbox configurations are
compatibility history, not the current playtest's feature list.

Authorities: `sources/Multiplayer_Post_Apocalyptic_Game_GDD_v0.2(1).docx`,
`sources/Multiplayer_Post_Apocalyptic_Game_Database_Design_v0.1(1).docx`, and
`sources/Post_Apocalyptic_Game_V1_Building_Settings(1).xlsx`. GDD v0.1 is superseded.
The sources were read only and their SHA-256 hashes were checked for changes.

## Confirmed inconsistencies

### 1. Town Hall can fall below its locked minimum — corrected

GDD sections 17 and 37 specify a minimum of 25% maximum HP. In
`game/ruins.py:64`, hostile damage clamps the Town Hall to **1 HP**.
The existing `test_structural.StructuralTests.test_hall_survives_and_retains_oxygen_and_electricity`
also expects 1 HP. The test therefore preserves the wrong rule.

A disposable level-1 Hall with 1,000 maximum HP was hit for 100,000 damage.
It survived at 1 HP instead of 250. Its usable housing fell to zero. Permanent
utility zones survive, but that does not preserve housing, storage or ordinary
staffed production. This makes the recovery anchor much weaker than intended.
The admin HP correction also accepts any positive Hall HP, so both paths need the
same invariant. Test the floor at every Hall level, repeated damage, occupant
injuries, storage loss, repair, upgrades and administrative correction.

### 2. Full storage does not throttle ordinary production or its XP — corrected

GDD section 13 says continuous production pauses when output cannot be stored,
input-consuming production avoids spending unusable inputs, and stalled workers
earn no production XP. `game/economy.py:209` clamps final quantities; production
rates and `game/progression.py:28` do not account for full output storage.
`docs/progression.md` explicitly describes XP continuing while overflow is discarded.

With a full 160-Food pool, the opening settlement still reported 8 Food/hour
production, 6 consumption and +2 net. After a minute Food remained 160 and the
Garden worker received the full 1/60 XP. Actual throughput is not reflected in
the rate/XP calculation. Consumption can create room for replacement production;
a correction must preserve that useful work while throttling only surplus, rather
than turning off all production merely because an interval starts full.

Add tests for full and nearly full pools, ongoing consumption, storage stalls,
partial throughput, converter inputs, lossy conversion at full shared storage,
reservations and equivalent long/offline versus small-step simulation.

### 3. Captures can create duplicate citizen names — corrected

GDD section 7 requires unique full names within a settlement and unchanged identity
after capture. `game/settlement.py:207` gives every settlement the same six starting
names. `game/capture.py:25` transfers those names unchanged without resolving the
collision. A disposable capture produced two living citizens named **Mara Vale**
in the receiving settlement.

Scavenged-survivor uniqueness is tested, but capture collisions are not.
Give newly created citizens identities that remain unique across potential
transfers, while preserving existing citizens' names and IDs. Existing-save
collisions need an explicit compatibility/display policy; silently renaming
captured people would violate the other rule. Births and floor arrivals also use
placeholder labels such as `New Citizen 1` and `Survivor 1-1` rather than generated
first names and surnames.

### 4. Midnight capture checks run after Bank processing — corrected

GDD section 36 locks captured-citizen desertion checks and integration before
ordinary daily morale/financial effects. `game/expansion.py:55` applies Bank accrual
and liquidation before `capture.daily`. A disposable boundary recorded
`bank_interest` followed by `captured_citizen_deserted`.

Debt modifiers and liquidation can therefore affect the state used for the
capture check at that same midnight. Correct the internal rollover order while
retaining the separate rule that midnight processing finishes before an attack
arriving at exactly midnight. Test capture, debt, liquidation, population recovery
and same-timestamp attacks together.

### 5. Population-floor survivors do not participate in birth demographics — corrected

Both `game/consequences.py:206` and the older `game/combat.py:45` floor-arrival path
create citizens with sex `unknown`. Birth eligibility in
`game/consequences.py:161` requires a male and a female at home.
After a disposable total population loss, rollover correctly restored six
citizens, but all six had `unknown` sex and birth eligibility remained zero.
That settlement cannot resume natural demographic growth without additional
scavenged/captured citizens, even after housing and supplies recover.

Use the same generated identity/demographic system for starting citizens, births
and recovery arrivals. Do not invent a guarantee of a mixed-sex group without
agreeing that additional rule; the defect is that all recovery arrivals currently
lack usable demographic data.

### 6. Administrator moderation still runs through the player server — corrected

The independent console and separate cookies work, and the player server rejects
`/admin` and `/lobby` writes. However, the player `/communication` route still
accepts `hide` and `restore`; `game/communication.py:57` executes the moderation
when the player account is an administrator. Its player panel also renders those
forms for admins.

A disposable authenticated Flask request on player port 8767 returned HTTP 303
and hid a board post. This is an authorized admin operation, not a privilege
escalation by ordinary players, but it contradicts the requested independent
admin suite and `docs/admin-operations.md`'s claim that the player app rejects
operator writes. Keep moderation in the console and test every operator action
against the player transport, including communication subactions.

### 7. Current citizen roster omits information needed to understand progression — corrected

The latest `prototype_v13` page does not show XP: `game/views.py:48` only displays
it for versions 7–9. The roster also omits sex, although birth eligibility depends
on it. GDD sections 7 and 33 specify those fields. The existing XP UI test only
uses the older progression configuration, so it misses this regression.

The disposable current Flask HTML confirmed both omissions. Test the current
shared-start configuration, not only the original feature activation version.

## Feature inventory

“Implemented” means a usable code path with regression coverage exists. It does
not mean every rule is correct, every edge case was retested here, or balance has
been validated by a complete multiplayer season.

| Requested area | Current status | Principal implementation / coverage |
| --- | --- | --- |
| V1 database and saved progress | Implemented: initial 40-table schema, constraints, history, transactions; additive account/admin/lobby tables | `database/create_database.py`, `game/settlement.py`; database/prototype/review tests |
| Accounts and login | Implemented: registration, salted password hashes, sessions, logout, password change, ownership and CSRF/origin checks | `game/accounts.py`, `flask_app.py`; accounts/Flask tests |
| Equal shared start | Implemented: reservations hidden behind a waiting lobby; one atomic host launch; all enabled features start at one time | `game/lobby.py`; playtest tests |
| Shared map / private ruins | Implemented: 40×40 map, common derelict layout, independent stored private loot, gradual clearing | `game/scavenging.py`; production/population tests |
| Civilian economy and upgrades | Implemented: Food, Water, materials, Oxygen, Electricity, storage, Town Hall progression | `game/buildings.py`, `game/economy.py`; food/production tests; full-storage issue above |
| Housing | Implemented: independently buildable workbook types, automatic quality/level/XP/seniority allocation, HP scaling, powered comfort | `game/population.py`, `game/recovery.py`; housing/population/recovery tests |
| Citizen progression | Implemented: work/construction/repair/combat XP, automatic levels, persistent HP and history | `game/progression.py`, `game/combat.py`; progression tests; latest roster and storage issues above |
| Citizen needs and population | Implemented: rations, shortages, exposure/evacuation, homelessness, unemployment, births, desertion, expulsion and midnight recovery | `game/needs.py`, `game/consequences.py`; needs/citizen tests; recovery-demographics issue above |
| Support buildings | Implemented: medical treatment, Engineering Workshop, Salvage Depot, Trading Post, Community Center, guards and patrols | `game/support.py`; defense/support tests |
| Repairs and removal | Implemented: paid repairs, Hall regeneration, drone servicing, automatic/manual repair drones, cancellation, demolition, ruin salvage | `game/repairs.py`, `game/maintenance.py`, `game/building_management.py`, `game/ruins.py`; maintenance/structural tests |
| Military production | Implemented: drone and munitions factories, six hardware types, batches/queues/repeat, compatible storage and pause conditions | `game/manufacturing.py`; manufacturing tests |
| Conflict | Implemented: war warning, protections, daily limits, resource/population/Credit/infrastructure raids, mixed assets, injuries, capture and reports | `game/combat.py`, `game/capture.py`; combat/expansion tests; identity/rollover issues above |
| Structural defense / damage | Implemented: interceptors, air/ground phases, turrets, occupant injuries, explosions, ruins and rebuilding shield | `game/structural.py`, `game/ruins.py`; structural tests; Hall-floor issue above |
| Allied defense | Implemented: direct treaty partners' eligible hardware, local-first/even drawing, real losses, no stacking/chains | `game/alliance.py`; allied expansion tests |
| Trading and public market | Implemented: reservations, atomic private exchanges, partial market fills, seller fees, discounts and Bank ledger | `game/trading.py`, `game/market.py`; trading/social tests |
| Diplomacy | Implemented: bilateral proposals, acceptance/rejection, coexisting treaties, war, cooldowns and peaceful recall | `game/diplomacy.py`; social/allied tests |
| Player communication | Implemented: private inbox/outbox, public board, moderation, news and read notifications | `game/communication.py`; social tests; operator separation issue above |
| Bank and Vaults | Implemented: loans, interest, repayments, investments, early withdrawal, debt morale, liquidation, Vault protection and Credit raids | `game/banking.py`, `game/vaults.py`; banking/expansion tests |
| Live rankings | Implemented: four category totals, normalized Overall, negative Wealth and shared tie ranks | `game/scoring.py`, `game/expansion_views.py`; scoring tests |
| Independent admin suite | Implemented: local separate launch/login, pause/resume, suspension, audited state corrections, moderation, announcements, diagnostics, logs and backup/restore | `admin_suite.py`, `game/admin_controls.py`, `game/diagnostics.py`, `manage.py`; admin tests |
| Complete season management | Deferred by user: only shared freeze/basic settlement and resource snapshot exist | `game/simulation.py:21`; review/expansion end-boundary tests |
| Final graphical/mobile experience | Partial: responsive server-rendered web UI, clickable scrollable SVG map and placement preview | `game/views.py`, `game/building_views.py`, `static/`; prototype presentation, not final art/navigation |

## Content and balance checks

- All **42 Buildings rows** have an implementation, including the added Vault.
  Independently compared **2,649 configured building-level numeric fields**,
  **36 manufactured-unit numeric fields** and **387 copied combat/economy/morale/
  scoring settings** with the workbook. All checked values matched. This verifies
  copied data, not that every setting is used correctly.
- Fresh disposable Alpha/Bravo settlements started at the same timestamp with
  the same resource package, six citizens, 64 common-position derelicts,
  `prototype_v13`, supply consequences and the expansion enabled.
- The starting Administrator supplies 2 Food and 2 Water/hour against six citizens'
  demand of 6/hour. The unchanged starting 120 of each therefore lasts **30 hours
  including Hall production**, rather than the workbook's approximately 20 hours
  before production. These are compatible statements.
- Through ordinary build/staff commands, **one Garden with one worker and two
  passive Rain Collectors** brought both net flows to **+2/hour**. Costs were
  85 Scrap total. One Rain Collector alone leaves Water at −1/hour. This verifies
  a viable opening; it is not a claim of an optimal strategy.
- A level-1 Scrap Yard adds the storage needed to accumulate the first Hall upgrade
  cost. Warehouse remains available at Hall 1 as explicitly approved. Scavenging/
  trade supplies missing materials; later processing unlocks follow Hall upgrades.
  Many existing progression tests fund their fixtures directly, so a complete
  no-grants progression from opening through all military technology remains a
  useful dedicated acceptance scenario.
- Ordinary citizen attacks cannot be sent from the starting population of six.
  Players need births or discovered/captured survivors before sending citizen
  raiders. Military manufacturing requires Hall 3. These are intended gates.
- A 30-day season provides 720 hours. At the base 1 work XP/hour, normal work alone
  reaches approximately level 5 (700 cumulative XP), not level 10 (2,700 XP), before
  productivity changes. Combat/construction accelerate that. This is a balance
  observation from the chosen curve, not a recommendation to change it.

## Approved rule choices retained

These are intentional decisions, not findings to undo:

- Warehouse at Hall 1; independently buildable housing types rather than GDD chains.
- Housing and ration morale are current modifiers while applicable.
- Citizen/drone prototype injury fractions: 10% win, 30% loss, 20% contested.
- Food shortage 6-hour grace / 2 HP/hour; Water 2-hour grace / 4 HP/hour, with the
  implementation's documented proportional reduction for partial supply.
- Approved air/ground drone phase behavior; strongest functioning support bonus
  without duplicate stacking, scaled staffing/condition; automatic medical slots.
- Workshop drone repair 10 HP/hour and 25% build-material health-fraction costs;
  repair drones add health-scaled 10 HP/hour to paid repairs.
- Exposure damage follows workbook survival time, 25% evacuation and current −10
  morale; ordinary desertion preserves six home citizens; expulsion costs 3 morale;
  birth security estimates 24 hours of stock plus production.
- Approved turret phases, occupant injury fraction, 180 HP/round explosions and
  clearing work derived from completed construction/upgrade work.
- Seller's market fee is rounded upward; Trading Post/treaty reductions multiply
  with a 2% minimum. Bank receives the fee.
- Allies contribute floored 25% eligible hardware, local first, even drawing, no chains.
- Focused capture 25%, cap three; incidental 2%, failed-raider 8%; captive morale 20
  and the approved elevated midnight desertion rule.
- Debt capped at twice original principal; approved liquidation order protects the
  Hall and citizens; outstanding borrowed principal is excluded from investments.
- All players start together in the present playtest. Closed post-launch enrollment
  differs from eventual GDD late joins but follows the user's shared-start request.

## Incomplete V1 features and unresolved source interpretations

1. **Advisor:** no named rules-based advisor, portrait, requested status report or
   advisor history exists (GDD section 32). Current supply/risk panels are useful
   but do not implement that feature.
2. **Notification coverage:** mail, market purchases, diplomacy, war, allied support
   and admin announcements have notifications. Construction completion, ordinary
   incoming/resolved battles, citizen births/deaths and finance events mostly use
   panels/reports/internal events rather than the promised notification feed.
   Public news is primarily treaty/war/raid news; milestone and Bank-condition
   news is incomplete.
3. **Admin balance configuration:** corrections and operational control exist, but
   the console cannot configure starting packages, rates, building settings,
   attack timers/limits or Bank parameters with safe-midseason versus next-season
   validation (GDD section 35). JSON editing is not that feature.
4. **UI/presentation:** no minimap, discrete zoom controls, final building/upgrade
   sprites or angled pixel-art presentation. The always-visible resource HUD,
   idle/population/morale/utility summary, time-to-full and resource drilldowns
   need further work. Existing utility outlines and scrollable map are present.
5. **Long-term seasons:** scheduled starts, late joining, next-season creation,
   full frozen maps/rosters/finances/treaties/standings, winner awards and persistent
   all-time season statistics are incomplete. Keep these deferred as requested.
6. **Ration health:** the implementation damages HP for actual supply shortages.
   It does not independently damage a well-supplied citizen for prolonged emergency
   rations. GDD section 12 and Citizen Economy emergency-ration notes suggest that
   consequence, but define no duration/rate. Specify it before implementation.
7. **Utility/storage source conflicts:** the workbook uses capacity plus geometric
   coverage; GDD section 14 describes zones alone. Existing implementation follows
   the workbook model. Workbook Utilities D23 retains inaccessible Cold Storage
   Food on power loss, while GDD section 13's generic overflow rule says excess is
   lost. Preserve current documented behavior pending a reconciled rules addendum.
   Town Hall utility radius also grows from 4 to 5 to 6 tiles in the workbook and
   code, while GDD section 17 says its radii remain fixed through upgrades. That
   source conflict affects expansion space and should be explicitly resolved.
8. **Damage/storage and drone-home interpretations:** reserved resources survive
   some storage losses; deployed drones can return to replacement homes after
   their original home is destroyed. These are documented/tested choices, but the
   GDD's generic overflow and assigned-drone destruction wording is broader.
   Confirm these semantics instead of silently changing existing tests.
9. **Rebuilding eligibility:** implementation counts operational buildings, so an
   unstaffed or unpowered surviving building can fail to count. Clarify whether
   “Town Hall only” means no surviving completed buildings or no functioning
   buildings. Existing docs describe the latter.
10. **Audit investigation:** randomized combat/loot and birth outcomes are retained,
    but normal/captive desertion events lack individual probability/roll/morale
    input snapshots. Seeds help reproduce random sequences, but do not record all
    historical inputs. The admin UI only displays recent events and basic integrity/
    reservation checks; semantic HP/name/demographic checks and searchable/exportable
    investigations are incomplete. Player battle rendering currently omits internal
    rolls, though raw battle-report JSON duplicates some internal audit data.

Research, specializations, citizen equipment/pathfinding, weather, food spoilage,
fire, day/night lighting, reconnaissance and external push notifications remain
explicitly outside V1. Public hosting has not been opened by this review. Native
mobile packaging and self-service emailed password recovery are not implemented;
admin-assisted password reset is available.

## Runtime and testing evidence

- Latest full regression result already saved: **557 tests passed in 1,791.444
  seconds** after test consolidation. No gameplay code changed for this review,
  and the full suite was not rerun here.
- This review reran **44 existing targeted tests successfully**: scoring, banking,
  independent admin suite, shared-start lobby, three birth checks and market
  conservation. A first selection mistakenly named a nonexistent `LobbyTests`
  class; the 37 real tests in that selection passed, and the corrected
  `PlaytestTests` selection then passed all seven. That was a selection error,
  not a gameplay failure.
- Separate controlled-clock temporary-save probes reproduced the reported
  mismatches, verified the viable opening and passed SQLite integrity/FK checks.
  These are review probes, not new permanent regression coverage or fixes.
- One hour of elapsed-time processing for the small opening fixture took about
  **7 seconds** on this computer. This is one illustrative measurement, not a load
  benchmark. Minute-grid progression and repeated state reconstruction remain
  expensive. The player resource poll also refreshes every active settlement for
  common-time rankings. Test long offline catch-up and concurrent players before
  inviting a larger group; do not infer capacity from the Waitress thread count.
- No player saves were mutated or reset, no source workbook/document was changed,
  no real accounts were created and no public tunnel was opened.
- This is a static/content audit plus focused execution. It does not replace
  a many-player, multi-week balance playtest, desktop/mobile browser usability
  checks or a broader security assessment.

## Suggested small correction increments

1. **Recovery invariants:** correct the Hall's 25% floor and capture-before-finance
   rollover order. Add cross-system tests and deliberately update the test that
   currently expects 1 HP to match the existing locked GDD rule.
2. **Citizen identity:** generated names/demographics for arrivals, capture collision
   policy for existing saves, latest-version XP/sex roster fields and regression tests.
3. **Production throughput:** actual storage-aware production, inputs, rates and XP;
   tests for consumption replenishment, conversion, overflow and offline equivalence.
4. **Operator separation and visibility:** remove player-route moderation, broaden
   diagnostics, then basic advisor and missing notifications. Keep each change small.
5. **Playtest readiness:** measure/fix offline and concurrent catch-up performance,
   run a no-grants end-to-end progression scenario, verify mobile controls, then
   discuss exposing only the player application. Admin balance controls can follow
   as a separate requested feature. Seasons remain postponed.

Every gameplay correction needs a reproducing regression test and the full
`python run_tests.py` before it is reported complete. Do not discard existing tests
or tune workbook balance to hide implementation defects.

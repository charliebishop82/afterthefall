# Current game review and remaining work — 11 October 2026

## Assessment and scope

The playable shared-start prototype contains the civilian economy, all workbook
buildings/upgrades, citizens, manufacturing, repairs, trade, diplomacy, combat,
banking, accounts and separate operator tools. This review covered the latest GDD
v0.2, database design v0.1, current workbook, approved decisions, implementation,
public controls and regression coverage. It extends the earlier content and
building/economy reviews. It is not a certification of a complete V1 or flawless
balance: the explicit gaps and validation limits below remain.

Current entry points are `serve_game.py` (Flask/Waitress, player port 8767) and
`admin_suite.py` (independent Flask/Waitress console, port 8768). Both use
`database/playtest.db`. The lobby waits for an administrator to launch the group.
Legacy `app.py` and `accounts_app.py` retain separate saves and older opt-in rules.
See [the main running guide](../RUNNING_THE_GAME.md) for Conda, packages, account
bootstrap, commands, backups and optional future hosting.

## Source precedence

The latest local GDD is `Multiplayer_Post_Apocalyptic_Game_GDD_v0.2(1).docx`.
GDD v0.1 is superseded. `Post_Apocalyptic_Game_V1_Building_Settings(1).xlsx`
controls building content and numerical balance; the database design controls
persistence. User-approved exceptions take precedence. Reference documents under
`sources/` remain unchanged; this file is an implementation addendum, not an edit
to the design sources.

The workbook's capacity-plus-coverage utilities, Hall radii 4/5/6 and inaccessible
Cold Storage retention on power loss are retained as numerical authority where
broader GDD wording differs. Warehouse at Hall 1, independently buildable housing,
current housing/ration morale, renewable Salvage Depot Scrap and the previously
approved combat, citizen, repair, capture, fee and Bank prototypes are retained.
See [approved choices](content-review-2026-10-11.md) and
[building/economy checks](building-economy-review-2026-10-11.md) for their values.
No workbook cost, production curve, combat weight or birth probability was retuned
by this review.

## Feature and regression coverage

“Implemented” means an available server-authoritative code path and automated
regressions. Coverage names identify the relevant test modules; they do not imply
exhaustive combinations or an actual completed multiplayer season.

| System / GDD sections | Current behavior | Principal regression modules |
| --- | --- | --- |
| Persistence / 3 | Original 40 STRICT tables, foreign keys, atomic changes, UTC clocks, retained lifecycle records; additive auth/lobby/operator metadata | database, prototype, review, runner |
| Accounts / 3, 30 | Registration, login/logout, salted password hashes, expiring sessions, password changes, ownership, CSRF/origin/Host checks; no email recovery or gameplay advantage from history | accounts, flask_playtest, admin_hosting |
| Start / 4, 5 | Same starting package/map and hidden prelaunch lobby; atomic shared start, beginner shield, explicit enrollment; enrollment closes at launch as requested | flask_playtest, renewable_opening |
| Map / 6, 18 | 40×40 shared geography, 64 private persisted ruins and independent loot, gradual scavenging and discoveries; clickable scrollable map and utility overlays | production, population, prototype |
| Buildings / 10–17 | All 42 types, 108 levels and 66 upgrades; costs, footprints, unlocks, placement, workers, jobs, damage, capacity, cancellation and demolition | building_catalogue, buildings, production, population, maintenance |
| Production / 11–14 | Food/Water and material flows, utility capacity/coverage, storage throttling, reserved inputs, productive XP, renewable Scrap at existing Salvage Depots | production_storage, renewable_scrap, renewable_opening, progression |
| Housing / 10 | Independent workbook types; automatic quality/level/XP/seniority allocation, HP-scaled capacity, powered comfort and homelessness | population, recovery, citizen_consequences |
| Citizens / 7–9, 12, 14 | Identity/sex/XP/levels, HP, current morale modifiers, needs/grace periods, evacuation, unemployment, births, desertion, expulsion, six-person midnight recovery | citizen_identity, progression, needs, citizen_consequences, review_completion |
| Town Hall / 17 | 25% hostile-damage floor, permanent utilities, Administrator production, reduced upgrade output, regeneration and automatic vacancy replacement; direct Administrator reassignment and raid deployment in current v13 | repairs, structural, review_completion |
| Manufacturing / 19 | Six hardware types; two factories, batch/repeat queues, paid-unit reservations, compatible physical homes, operational pauses and persistent drone HP | manufacturing, feature_http, maintenance |
| Repairs / 16 | Citizen crews, paid building repair, drone servicing, manual/automatic repair drones, capacity recovery and salvage of wrecks | repairs, maintenance, structural |
| Combat / 20–26 | War warning, blind incoming countdown, daily allowances/home floor, mixed assets, air/ground/turrets, interception/explosions, resource/population/Credit/infrastructure raids, return capacity and private reports | combat, defense_support, structural, expansion, allied_expansion |
| Capture / 23, 36 | Identity and health retained, low morale, one elevated midnight check then integration, before finance/population recovery; audit records actual morale/probability/roll | expansion, citizen_consequences, review_completion |
| Support / 9, 16, 23 | Strongest operational staffed support effects; medical slots, workshops, salvage/trade/community effects, guard radii and patrol | defense_support, maintenance, allied_expansion |
| Diplomacy / 27 | Proposal/accept/reject/cancel, coexisting treaties, peace/NAP cooldowns, war declarations, immediate recalls; direct allied 25% eligible hardware, local first/even drawing, no chains | social, allied_expansion, combat |
| Trade / 28 | Reserved private offers, atomic exchanges, expiry, public partial fills, whole Credits, seller fee/discount/floor/rounding and paired ledgers | trading, social |
| Bank/Vaults / 25, 28 | Loan limits/interest/debt cap, conservative investment eligibility, term returns, early-withdrawal forfeiture, liquidation and powered Vault allocations | banking, expansion, expansion_http |
| Scoring / 29 | Population/military/wealth/development totals, condition, committed assets once, negative wealth, shared normalization and tie handling; public totals hide inventories | scoring, expansion_http |
| Communication / 31 | Persistent private mail, board, operator-only moderation, public treaty/war/raid news, read notifications | social, admin_suite |
| Advisor / 32 | Named rules-based Ash panel, live warnings, on-demand saved reports, ten recent reports shown; no AI dependency or balance changes | review_completion |
| Notifications / 32 | Existing messages/market/treaties/war/allied notices plus incoming/resolved attacks, construction/upgrades, repairs, manufacturing, survivor/citizen events and finance | social, review_completion, building_catalogue |
| Operator suite / 35 | Independent authentication/cookie/server, explicit roles, pause/resume, suspension/recalls, audited compare-and-set corrections, password reset, board moderation, announcements, diagnostics and searchable JSON event export | admin_suite, admin_controls, review_completion |
| Boundaries / 4, 36 | Idempotent catch-up, final-window restrictions, simultaneous-attack ordering by arrival/ID, capture→finance→population/allowance midnight processing, overlap-aware frozen clocks | simulation, combat, expansion, admin_controls |
| Season endings / 4, 29–30 | Partial freeze/settlement/score retention exists; complete rollover/archives/awards remain intentionally deferred | expansion, trading, structural |
| Presentation / 6, 33–34 | Browser interface and SVG prototype map; final art/minimap/zoom and HUD refinement remain incomplete | prototype, flask_playtest |

## Corrections made in this review

1. Damaged construction now loses Development/settlement-value credit for recorded
   hostile damage. Completed-work value is counted once, rather than multiplying
   progress twice or ignoring the damage. Existing workbook scoring weights stay
   unchanged; legacy undamaged work remains supported.
2. Current Administrators can move directly into ordinary construction/production
   assignments or offensive raids. Validation runs before the assignment changes;
   rejected actions roll back. The highest-level available citizen (then XP and
   seniority) replaces them, otherwise the role stays vacant and the Advisor warns.
   Vacancy synchronization also fills the role when someone becomes available.
   Deployed citizens remain unavailable and six citizens must remain home.
3. Normal desertion logs now retain each checked citizen's morale, probability,
   roll, current home count, floor blockage and outcome. Captive checks retain the
   actual inputs/roll for both integration and desertion. Birth checks also retain
   home demographics/morale, housing, accessible stock and production/consumption.
   This adds evidence; it does not add random draws or change outcome formulas.
4. Notifications are written in the same transaction as their underlying events.
   Repeat processing of a completed action does not issue another completion.
   Clock updates are not notifications. Player messages exclude internal random
   rolls, and incoming attacks do not disclose attacker identity or composition.
5. Read-only diagnostics now also check citizen/building/drone HP, unknown building
   types/levels and live assignment ownership/lifecycle. Existing duplicate names
   are warnings distinguished by IDs, not automatic renames or failed health
   checks. Old catalogue-less Town Hall saves are recognized.
6. Operator logs support exact settlement/type filters and paging before an event
   ID; JSON downloads export up to 100 matching events per request. Queries bind
   filter values; the endpoint retains operator authentication. No save repair or
   clock advancement occurs. Passwords/session tokens are not event exports.
7. A basic Advisor now reports supply decline, storage pressure, housing, morale,
   damage, idle citizens, stalled projects, utility/operating problems and debt.
   Requests catch up the owner's clock, save a report and are limited to one per
   minute. Live render/history reads do not modify data. Finished archives reject
   new saved reports. The portrait/final visual treatment remains future work.
8. Administrative suspension now tells the player that an administrator must
   reactivate the account. Only an old supply-frozen sandbox suggests replenishing
   Food/Water through trade. Module descriptions and old guide status banners now
   distinguish current shared playtests from historical opt-in increments.

9. Birth supply qualification now uses the current Food/Water ration policy for
   the prospective newborn as well as the existing population. Exactly sufficient
   stock plus production qualifies; a small deficit in either resource does not.
   The configured probability and housing slowdown remain unchanged.

10. Away drones are kept deployed through combat and reward delivery, then checked
    for compatible return slots. Home destruction warns the owner. Loss on return
    is explicitly recorded in the battle report without reversing earned rewards.
11. Rebuilding eligibility now counts every surviving non-Hall building/site,
    including unstaffed or unpowered ones, as requested. Hostile destruction,
    24-hour duration and the three-functional-building rearm rule remain intact.

## Missing work and suggested increments

These are remaining features or acceptance work, not newly discovered reasons to
retune the game's approved rules. Complete seasons stay deferred as requested.

1. **Operator balance controls:** add versioned configuration snapshots and audited
   editing of starting packages, season length, attack limits/timers, economy/Bank
   values, resource rates and building parameters. Show a validated before/after
   diff. Separate live-safe numeric changes from next-season structural changes;
   settle all affected old rates before applying live changes. Preserve historical
   configuration with archives and each audit. Raw JSON editing currently requires
   a restart and is not a safe midseason balance editor. This is a substantive
   missing GDD feature, not something to describe as already implemented.
2. **Playable progression and hosting acceptance:** extend the now-verified no-grants Hall 3 campaign
   through Electronics conversion, military manufacturing and damage/recovery; test
   multiple concurrent clients and day-length offline catch-up. Shared ranking
   refresh can hold a write transaction longer than SQLite's default five-second
   busy wait (last 10-player one-hour probe: about 11.5 seconds). Bound/schedule
   catch-up while preserving attack/UTC ordering before a larger public playtest.
   Test restart, pause/resume, backup/restore and public HTTPS-origin configuration.
3. **Player information and navigation:** sticky complete HUD with resource
   drilldowns/time-to-full, category leaderboard views, collapsible minimap with
   utility overlays, discrete zoom, mobile interaction checks and the Advisor's
   final portrait. Current SVG building labels are not the promised distinct
   building/upgrade pixel art. Do not call visual V1 complete yet.
4. **News completeness and audit polish:** add meaningful public milestone/Bank
   condition transitions without revealing private stock, richer Advisor defense
   warnings and proactive stored-message history, plus broader semantic diagnostics
   (job/hardware/home consistency) and paged intervention-history export. Current
   event exports are bounded chunks, not a one-click whole-season archive.
5. **Seasons, later:** scheduled starts/late joining, next-season creation, complete
   frozen map/roster/finance/treaty archive, category awards, wins and all-time stats.
   Keep these inactive until requested.

The user confirmed the remaining interpretation rules during this review:
- Away drones finish their mission and deliver earned rewards after loss of their
  original home. An owner warning requests replacement storage. On return they
  relocate to free compatible slots, or are destroyed without reversing rewards.
- Rebuilding protection requires every non-Hall building/site to be destroyed;
  being unstaffed or unpowered does not qualify. The existing three-functional-
  building rearm requirement remains unchanged.
- Emergency rations retain current morale modifiers and shortage-based HP loss,
  with no separate prolonged-ration health penalty.

Trade escrow remains protected during some capacity losses; release/settlement
then follows existing capacity checks. This intentional anti-double-spend behavior
is disclosed rather than silently rewritten under a generic overflow sentence.

Research, specialization, citizen equipment/pathfinding, aging/family trees,
weather, spoilage, fire, day/night, reconnaissance, badges and external push remain
outside V1. Public hosting has not been opened. No credentials or default admin
password were created by this review.

## Validation and limits

The 84 focused structural-combat, support and review regressions passed.
The full **612-test** regression suite passed in **1746.668 seconds**.
The runtime/test/reference snapshot matched the frozen validation manifest.
Installation checks both the staged snapshot and unchanged project before-images,
backs up code and all saves, and preserves reference documents. All tests use temporary
saves and controlled clocks/randomness. Earlier regression expectations remain
intact. Source numeric audits already cover 2,649 building fields, 387 settings,
36 hardware fields and 336 metadata comparisons, with approved exceptions noted.
A separate disposable no-grants campaign used only normal player actions to build
a Garden, two Rain Collectors, a staffed renewable Salvage Depot, Scrap Yard,
Warehouse, Wind Turbine and Recycler, extend Oxygen coverage and scavenge, then
complete both Hall upgrades. It reached Hall 3 in 65.7125 simulated
hours with seven living citizens, positive Food/Water and successful read-only
diagnostics. Probe wall time was 781.0 seconds; this scripted
strategy and its many placement searches are not a production load benchmark.
It does not yet cover an Electronics converter, military chain or damage recovery.

Tests and source comparison do not establish strategy fairness, long-term balance,
or freedom from all defects. Those require the acceptance/playtest increments
above. The earlier measured performance limits remain applicable.

Post-install verification: both local login endpoints returned HTTP 200 after
restarting the player and operator services. All eight saves retained their game
rows and passed SQLite integrity/foreign-key checks; all four reference documents
retained their hashes. The installed catalogue audit reported zero errors.
The 58 changed/new files were backed up under `database/backups/before-complete-review-20261011T183017734298Z` before installation.

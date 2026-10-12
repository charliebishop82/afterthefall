> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

> **Historical review.** For current feature coverage, open findings and suggested
> correction increments, see [the 11 October 2026 content review](content-review-2026-10-11.md).
> The deferred lists below describe earlier increments and are not the current feature list.

# Prototype consistency review — 2026-09-30

Reviewed the current implementation, regression coverage, GDD v0.2, V1 database
design, workbook-derived configurations and the user's approved exceptions.
This is an implementation review, not a claim that the entire GDD is implemented.

Subsequent increments now implement opt-in ration/shortage consequences,
military manufacturing, support buildings, guards/patrols and basic drone combat.
See [supplies](needs.md), [manufacturing](manufacturing.md), [support](support.md)
and [drones](drones.md). Historical validation below covers the review baseline.

## Implemented scope

| Area | Current behavior |
| --- | --- |
| Persistence | V1 SQLite schema, foreign keys, transactional commands, saved progress and event/history records |
| Accounts | Registration, login/logout, password hashes, expiring sessions, ownership, CSRF checks and shared season |
| Civilian economy | Food, Water, Oxygen, Electricity, material conversion, storage and workbook upgrades |
| Construction | Placement, rotation, costs, staffing, diminishing returns, completion and utility checks |
| Scavenging | Private persisted loot, incremental delivery, clearing and rare survivor discoveries |
| Citizens | Automatic housing, current comfort modifiers, natural healing, productive-work XP and automatic levels |
| Maintenance | Paid crew repairs and staffed Town Hall regeneration |
| Trading | Private proposals, reservations, acceptance/rejection/cancellation, expiry and atomic exchanges |
| Conflict | War warnings, protection, citizen resource raids, deployment, injuries/death, loot and private reports |
| Boundaries | Midnight allowances/population floor, final-window action checks and shared end-of-season freeze |

## Confirmed defects corrected

1. **Supply-freeze boundary:** commands validated activity before catch-up, but
   did not recheck a reached shortage freeze. Staffing, construction and scavenging
   could change an already frozen settlement. These commands now retain the
   elapsed-time freeze and leave the requested action unapplied.
2. **Shared season end:** the first player's request marked the season finished,
   leaving other players behind in simulation and still active. Every active
   settlement now settles to the end before the shared finished state is published.
   Frozen settlements retain their freeze, all settlements are archived, unfinished
   jobs are cancelled, and final resources are recorded for each settlement in one
   transaction. Due battles resolve first, including exact-end arrivals; later
   battles return committed citizens and refund the allowance once.
3. **Duplicate survivor names:** independently saved discovery outcomes could use
   the same generated full name. Arrival now selects an unused identity and persists
   it with the outcome. Existing citizens are never renamed; repeat processing does
   not duplicate arrivals. Population-floor arrivals use the same uniqueness check.
4. **Outdated documentation:** the README described implemented features as future
   work. It now presents the current entry points and scope. Earlier increment guides
   link here so their historical deferred lists are not mistaken for current scope.

## Approved interpretations retained

- Warehouse unlocks at Town Hall 1, as approved; the source workbook is unchanged.
- Housing types are independently buildable with their workbook levels and footprints.
- Housing morale is a current modifier; homelessness has a separate one-time penalty.
- Repairs retain the approved prototype rates and costs.
- Combat injury is maximum HP × 10% for a clean winner, 30% for a clean loser,
  or 20% for a contested fight. No capture or structural damage is added.
- Workbook numerical values control utility capacity/radius and Cold Storage behavior.
  Existing geometry, simulation-minute updates and raid tie-breaks remain documented
  prototype interpretations.

## Still missing, deliberately deferred (updated 2026-10-08)

- Oxygen exposure and ongoing homelessness damage; unemployment effects, broader
  morale drift, desertion, births and citizen expulsion. Food/Water shortage
  consequences and current ration morale are implemented.
- Structural attacks, destroyed-building salvage and rebuilding. Voluntary
  demolition/cancellation, Repair Drone actions and drone servicing now work.
- Missile/interceptor use, turrets, capture and allied defense. Manufacturing,
  offensive drone resource raids, air/ground drone defense and guards/patrols work.
- Public market, Trading Post fee benefits, loans/investments, Vault Credit raids,
  general treaties, messaging, public news, rankings and scoring.
- Scheduled/new seasons, complete historical snapshots/standings, administration
  and moderation, password recovery, public hosting and cross-platform packaging.

This remains a local development prototype. Existing settlements opt into supply
consequences; those without opt-in retain the older shortage freeze. The two entry
points use separate saves, and only account mode supports multiplayer conflict.
Shared season-end snapshots still record resources rather than the full GDD archive.
Deferred schema tables do not imply usable gameplay features.

## Suggested next increments

1. Missile/interceptor use, with explicit structural-damage rules.
2. Destroyed-building salvage and rebuilding; drone servicing and voluntary removal are implemented.
3. Complete seasons and scoring before broader financial/diplomatic expansion.

Each increment must preserve previous tests and add cross-system boundary checks.
All feature tests use disposable saves and controlled clocks.

Validation: all 262 tests passed (254 prior, eight new) in 750.917 seconds. Both existing saves passed read-only integrity and foreign-key checks, with no duplicate citizen names. Source documents, prior tests, and balance configurations were verified unchanged.


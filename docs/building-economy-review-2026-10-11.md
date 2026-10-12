> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# Building, economy and progression review â€” 11 October 2026

## Scope and authorities

Checked the latest GDD v0.2, Building Settings workbook, V1 database design,
current code, and the user's approved prototype interpretations. Synced sources
remain read-only. The workbook supplies numerical balance; the GDD supplies
behavior where the workbook does not specify it. Independent housing types,
current housing/ration morale, and Warehouse availability at Town Hall 1 remain
as approved. Full season rollover remains deferred.

The catalogue has **42 buildings, 108 implemented levels, and 66 upgrade steps**.
Comparison found no unexplained differences across 2,649 building-level numeric
fields, 336 catalogue metadata checks, 387 copied settings, and 36 manufactured
unit values. The Warehouse unlock is an explicit exception. Renewable Scrap is
a new approved extension, not a workbook transcription correction.

## Findings and implemented correction plan

1. **Remove the long-term material dead end.** Each settlement receives 64 finite
   ruins containing 1,216â€“2,808 base Scrap before bonuses. One of every building
   costs 3,155 Scrap / 2,225 Metal / 261 Electronics at level 1. Building every
   type and paying every sequential upgrade costs 9,280 / 9,950 / 1,511, before
   conversion inputs, repairs or hardware. Trade and raids redistribute supply;
   they cannot replenish an exhausted world. The user approved renewable Scrap.
2. **Use the existing Salvage Depot as the renewable source.** Staffed external
   salvage expeditions produce 8 / 12 / 18 Scrap per effective worker-hour at
   levels 1 / 2 / 3. Existing costs, footprint, unlock, worker limits, Oxygen
   demand, and support bonuses remain workbook values. Output scales with health,
   morale, citizen levels and building condition. It needs no electricity, extra
   input resource, or consumption of map ruins. Its maximum base output is
   16 / 36 / 72 Scrap/hour with all 2 / 3 / 4 worker slots filled. This rate is
   explicitly a configurable prototype choice in expansion_v1.json.
3. **Preserve useful-work and storage rules.** Renewable input resolves before
   converters, irrespective of building IDs. Production shares incoming material
   space with scavenging, respects reserved inputs, and pauses or throttles when
   output cannot fit. XP follows useful output. The Depot's existing scavenging
   speed/yield support stays separate and does not multiply its own new output.
4. **Make purchase controls agree with server rules.** Upgrade and repair buttons
   now use unreserved materials. The general building catalogue displays Scrap
   production and no longer describes every building as a Food building.
5. **Reduce state-loading overhead.** Cache versioned configuration text while
   parsing independent snapshots; replace the expensive catalogue deepcopy with
   an independent JSON copy; avoid reloading unchanged finance/capture stages;
   skip shared-refresh participants already at the requested time. Add an index
   for latest per-settlement, per-event-type clock lookup, including an idempotent
   addition to existing account saves. No history or game rows are removed.
6. **Keep the checks reproducible.** Add a standard-library-only audit_buildings.py
   command, detailed JSON catalogue evidence, regression coverage of every upgrade,
   useful renewable output, compatibility activation, and a genuine no-grants
   starting-package opening. Existing regression expectations remain unchanged.

The correction is active in expansion-enabled games, including fresh shared
playtests. Earlier sandbox versions retain their opt-in feature progression.
Restart services after editing configuration files so cached rules reload.

## Resource and unlock paths

| Resource or capacity | Bootstrap and continuing supply |
| --- | --- |
| Food | Town Hall + Garden at TH1; Greenhouse at TH2; Hydroponics at TH3 |
| Water | Town Hall + passive Rain Collectors at TH1; Well/Pump at TH2; Purification at TH3 |
| Scrap | Starting package and private ruins; staffed Salvage Depot at TH1 renews supply |
| Metal | Starting 40 and scavenging bootstrap TH2; Recycler converts renewable Scrap from TH2 |
| Electronics | Starting 10 and scavenging bootstrap TH3; Electronics Fabricator converts Scrap + Metal at TH3 |
| Oxygen | Town Hall and self-starting Oxygen Gardens; powered Generators and staffed industrial production expand capacity |
| Electricity | Town Hall and self-starting Solar/Wind; staffed Generator Plants at TH3 |
| Shared material storage | Town Hall, TH1 Scrap Yard, and approved TH1 Warehouse; repeatable storage buildings and Warehouse upgrades |
| Hardware | Compatible factories, bays/silos, workers and utilities at TH3; Metal and Electronics are renewable by then |
| Credits | Starting package, transfers/market, Bank loans/investments and approved raids; buildings do not directly mint Credits |

TH1 Hall storage is 250. Adding a 250-capacity Scrap Yard gives **500**, enough
for the first Hall upgrade's **380** total materials. For TH3, TH2 Hall storage
375 plus a level-1 Warehouse 450 gives **825**, enough for the **725** upgrade.
Another Scrap Yard is also an alternative. Storage is a shared combined-material
limit, so affordable individual resource totals still must fit together.

Ruins supply at least 280 Metal and 64 Electronics before bonuses across the
full map. This supports the bootstrap to converters, but requires scavenging and
Oxygen expansion; the starting package alone is not intended to fund every tier.
A Recycler and Fabricator still consume inputs and require operational utilities.
Renewable Scrap does not bypass those unlocks or staffing decisions.

All declared upgrade steps were exercised for destination costs, work duration,
saved completion, retained damage percentage and worker release. One-level
buildings deliberately have no upgrade. Independent housing types are retained;
no housing chain or growing footprint was invented in conflict with the workbook
and the user's housing decision.

## Scaling and fairness

Supply calculations account for actual productivity, input availability, shared
storage, reserved stock and utilities. Duplication is prevented by transactional
commands and saved progress. Utility providers can self-start where the rules
allow, but mutually dependent disconnected utility buildings do not bootstrap
one another. Production support bonuses use the existing strongest-building
rule. All players receive the same starting package, shared map geometry and
start time; private loot and population outcomes remain random as designed.

Higher Food/Water tiers increase productive capacity sharply. This is the
workbook's curve, not a new rebalance. Storage-aware output and XP prevent idle
full-stock production from creating extra output or levels. Extra workers still
consume Food/Water and require housing, Oxygen and infrastructure. Scrap rates
should be monitored during actual play: resource abundance can change the
relative value of scavenging, loans, repeated Depots and raids even when the
calculations are correct.

Load measurements and the final regression result are recorded below after
validation. Small synthetic worlds do not prove late-game performance or balance.
A multi-day multiplayer playtest remains necessary before claiming fair pacing,
a balanced dominant strategy, or safe capacity for a large public game.

## Remaining validation and suggested next increments

1. **Play a complete progression route:** start without grants, reach TH2 and TH3,
   operate both converters and a hardware factory, then verify repair/raid recovery.
   The current no-grants regression covers a sustainable renewable opening; the
   entire multi-day route is not yet an automated campaign test.
2. **Test real concurrent and long-offline load:** shared rankings currently advance
   players inside a write transaction. Long catch-up can delay other writers and
   exceed SQLite's default busy timeout. Before a larger public playtest, measure
   simultaneous clients and multi-hour/day downtime, then implement bounded or
   independently scheduled simulation processing if needed. Keep attack order,
   UTC rollovers and financial/capture boundaries unchanged.
3. **Tune only from playtest evidence:** compare development, production, military
   and trade strategies. Proposed changes to workbook costs, output curves, birth
   rates or combat balance require an explicit versioned balance change.

The earlier content review also lists advisor/notification coverage, operator
balance controls and UI polish. Existing documented escrow-overflow, rebuilding
eligibility and deployed-drone-home interpretations remain separate design
questions; this building/economy correction does not silently change them.
Workbook utility capacities, Cold Storage retention and Hall radii 4/5/6 remain
numerical authority where the broader GDD wording differs, with that difference
recorded rather than hidden.

## Load measurements

Fresh disposable worlds on this computer, same configured map/start and a shared
requested timestamp; three five-second advance trials per size:

| Players | Median five-second shared refresh | One-hour shared catch-up |
| --- | ---: | ---: |
| 5 | 0.283 s | 5.742 s |
| 10 | 0.501 s | 11.541 s |

Both cohorts reached the same timestamp and equal resource packages, and passed
SQLite integrity/foreign-key checks. These are serial fresh-world simulation
measurements, not HTTP concurrency tests or late-game load tests. Compared with
an earlier warm probe, avoiding redundant finance/capture reads reduced the
10-player one-hour catch-up from about 34 s to about 11.5 s. Timing varies with
system load; the regression suite was also running during the final probe.
An earlier measurement spanning a long host interruption was discarded as a
performance estimate. Its correctness assertions passed.

Long catch-up can still hold a write transaction beyond SQLite's default busy
wait, so opening a large public playtest remains a separate readiness increment.

## Final regression validation

**593 tests passed in 1,548.372 seconds**, with no failures, errors or skips.
This includes all 578 earlier regressions and 15 new tests. Existing expectations
were not weakened or removed. Coverage includes every one of the 66 upgrade
steps, independent cached/overlaid rules, transient old-version activation,
renewable-source staffing/damage/Oxygen/storage/XP, feed ordering, indexed clock
lookup, shared refresh idempotence and a real no-grants opening.

Only disposable saves and controlled clocks were used for testing. The installed
code is backed up before replacement; source documents are unchanged. No runtime
package was added. Current saves are preserved; account-mode startup adds the
latest-clock index idempotently. This validation establishes the tested contracts,
not a claim that every possible defect or balance issue has been eliminated.

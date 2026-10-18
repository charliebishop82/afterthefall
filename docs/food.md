> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# Food and construction increment

> This guide records its original increment. Later implemented features and current limitations are listed in [the consistency review](review.md).

## Playable now

Place a Garden beside the Town Hall. It costs 35 Scrap, occupies 2 x 2 tiles,
and takes 15 minutes with one healthy level-1 builder at normal morale.
Assign an unassigned citizen as its builder, then start time. More builders help
with diminishing returns. Remove all builders to pause a project without losing
progress. The season's Pause time control freezes construction as well as supplies.

Builders return to the unassigned roster at completion. Assign Food workers
separately. A Garden supports two Food workers and adds 10 Food storage at full
health. One normal worker adds 6 Food/hour; together with the Administrator's 2,
this exceeds the six citizens' consumption of 6. Water still decreases.

Select empty land on the map or enter zero-based column/row coordinates. Rotation
is supported for rectangular buildings. Placement rejects overlap and footprints
extending beyond the map, before spending anything. Sites reserve their footprint
immediately, even with no builders. Buildings cannot be moved.

## Food progression and Town Hall upgrades

The workbook's Garden has maximum level 1; it does not turn into a Greenhouse.
Town Hall level 2 unlocks separately constructed Greenhouses. Town Hall level 3
unlocks Hydroponics Facilities. Both advanced Food buildings support levels 1–3.
Their incremental costs, one-builder durations, HP, slots, output, storage and
utility demands are copied from the workbook into `config/prototype_v3.json`.
The catalog and upgrade panels show costs and the next level's benefits.

Town Hall upgrades use builders and update its housing, storage, Food/Water
production, and utility values. Its Administrator continues at reduced output
during upgrades. Food buildings stop producing during upgrades, retain existing
Food workers, and resume at the new level when completed. Existing storage remains
available during upgrades. Damage percentage is preserved when upgrading; upgrades
do not provide a free repair. New sites gain HP with construction progress.

Full material cost is paid once when a project starts. A stale upgrade form cannot
silently buy the following level after completion. Worker assignments and releases
settle elapsed time at the old rates first. Work finishes at the correct timestamp,
then the remaining offline interval uses the new production/storage values.
There is no global project limit; citizens are the practical limit.

The normal starting materials cannot fund a Town Hall upgrade. These controls
are implemented and tested with separate funded fixtures, but material gathering
must be added before the later progression is reachable in a normal new save.
There are no free player supplies or hidden balance changes in this increment.

## Utilities and explicit prototype interpretations

The workbook is the numerical balance authority; GDD v0.2 is the gameplay
authority. The workbook's Utilities sheet specifies coverage plus generation
capacity, whereas the earlier GDD describes geometric zones alone. This increment
uses the workbook's capacity model with the prototype's approved 50% coverage threshold.
Only the Town Hall currently supplies utilities. Oldest operational Food buildings
receive capacity first; idle/unfinished buildings do not consume it. Staff remain
assigned when utility capacity is insufficient and resume when it becomes available.
Production stops at or below 25% HP; above that it scales with condition.

Some exact formulas are not settled in the sources. The following small,
configurable prototype interpretations are isolated for future review:

- Production values are per normally productive worker, following the GDD's
  ordinary worker-slot contribution rule; they are not multiplied again by slots.
- Workbook construction minutes represent one normal worker's equivalent work.
  Crew speed is the sum of citizen productivity divided by sqrt(worker count).
  This gives diminishing returns without reusing the unrelated scavenging curve.
- Town Hall Administrator productivity is 50% during its upgrade. The GDD says
  reduced efficiency but does not quantify it.
- Coverage counts footprint tile centers inside a rounded zone measured from
  the Town Hall footprint. The workbook's radius increases by Town Hall level
  (4/5/6), taking numerical precedence over the GDD's earlier fixed-radius wording.
- Health, level and morale use the existing resource-increment productivity
  formula. Construction XP and citizen progression remain inactive.

These are implementation interpretations, not amendments to the source files.

## Boundaries still inactive

Construction can be placed outside coverage, but exposure work is blocked and
existing crews idle if coverage is lost. Oxygen injury/evacuation needs the future
citizen survival system. Additional utility buildings, gathering, cancellation,
demolition, repairs, spoilage (not part of V1), combat and multiplayer are not enabled.
At season end unfinished projects stop and retain spent materials/progress in the
archived state; full end-of-season settlement and scoring remain future work.
New projects cannot start in the final three hours. Supply depletion still pauses
the prototype before health consequences; construction cannot bypass that pause.

## Save compatibility and verification

Existing SQLite schema version 1 is unchanged. Old v1/v2 saves remain on their
configuration until the first successful building command explicitly enables v3
and records that transition. Invalid commands roll back spending, work and history.
Source documents and older configurations remain untouched.

Run `python run_tests.py` for the complete regression suite. New checks cover the
workbook data, placement/rotation, spending/rollback/concurrency, staffing, partial
and completed work, pause/offline boundaries, utility coverage/capacity, condition,
all Food levels, both Town Hall upgrades, unlocks, season boundaries, and HTTP forms.
Tests use disposable databases and controlled clocks, never the player's save.

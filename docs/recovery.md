> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# Citizen recovery and housing morale

> This guide records its original increment. Later implemented features and current limitations are listed in [the consistency review](review.md).

Configuration v6 activates through **Enable citizen recovery**. Earlier saves
retain their earlier rules until this explicit action. It also enables the
existing housing and civilian economy if needed, retaining health, base morale,
materials, loot, survivor opportunities, and construction progress. No SQLite
schema migration or external dependency is needed.

## Natural healing

The workbook's Citizen Economy `natural_heal_rate` supplies **2 HP per hour**.
In this increment healing requires accessible Food, Water, and an automatically
assigned usable home. Full-health citizens gain nothing; maximum health is the
starting HP plus the configured per-level increase. Zero-HP citizens never heal
or resurrect. Unsafe housing and inaccessible Food do not qualify.

To keep changing productivity predictable and independent of browser refresh
frequency, health is updated on a fixed simulated-minute grid. Qualifying seconds
are accumulated between boundaries, including fractional minutes before/after
housing changes or survivor arrival. Health updates change production and work
speed for the next interval. This is a documented prototype approximation to
continuous recovery, with a maximum display delay of one simulated minute.

Pause/resume shifts the recovery grid by the paused duration and retains earned
partial-minute credit. Paused, suspended and finished settlements do not accrue
recovery. The existing automatic supply-depletion pause remains active. A recovery
clock and pending credit are stored in game events; HP changes, elapsed resources,
work progress, and clock updates share the existing transaction. A failed update
rolls them all back. No background timer runs when the app is closed; reopening
processes the same elapsed-time boundaries.

## Housing morale

At the user's request, housing values are **current modifiers**, not daily morale
increments. A citizen keeps their saved base morale, and their effective morale
is clamped to 0–100 after adding their current home's workbook `Morale_Bonus`.
Tent penalties disappear when the citizen leaves that tent. House/Apartment
bonuses disappear when housing becomes unusable. Repeated reads never add bonuses
to saved morale. The v5 one-time -10 base-morale penalty for becoming homeless
remains separate and unchanged.

Utilities `optional_power_housing_bonus` supplies **+1 morale** for Houses and
Apartment Blocks with at least 75% functioning Electricity coverage. Optional
comfort adds no mandatory power demand and loss of power never removes housing
capacity. Housing priority includes this comfort bonus when ranking home quality.
Workers, builders, scavengers, and the Administrator use effective morale in their
existing productivity formula. Utility and housing allocation are resolved from
base morale to avoid using a source's own unreachable comfort to start that source.
If their feedback oscillates, only consistently usable housing capacity is kept.

The roster shows effective morale and its housing modifier. A recovery panel
shows maximum HP and why each citizen is or is not recovering.

Medical buildings and their bonuses, daily morale drift, rationing consequences,
ongoing homelessness damage, exposure injuries, births, population-floor recovery,
desertion, and combat remain inactive. The source workbook and GDD are unchanged.

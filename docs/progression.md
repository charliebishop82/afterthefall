> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# Citizen XP and automatic leveling

> This guide records its original increment. Later implemented features and current limitations are listed in [the consistency review](review.md).

Configuration v7 activates explicitly with **Enable citizen progression**. It
also enables the prior civilian economy, housing and recovery rules if needed.
Existing XP, HP, morale, resources, projects and persisted survivor/loot outcomes
are retained. Earlier configurations and source documents remain unchanged.
There is no schema migration and no new package dependency.

The Citizen Economy workbook supplies cumulative thresholds for levels 2–10:
100, 250, 450, 700, 1000, 1350, 1750, 2200 and 2700 XP. Productive work earns
1 XP per equivalent hour. Construction/upgrades earn 1 XP per 30 minutes of
actual equivalent work. XP remains cumulative after reaching level 10.

The Administrator and operating production workers earn XP scaled by their
actual health/morale/level productivity, building condition, upgrade efficiency,
and converter input availability. Operating utility workers qualify too. Stalled
work and idle citizens earn none. Continuous production earns XP only for useful
throughput: replacement supplies consumed during the interval still qualify,
while storage-limited work earns proportionally less or no production XP.
Input use and XP share the same interval calculation.
Passive buildings award no XP because they have no production workers.

Construction and scavenging crew credit follows actual equivalent work completed,
shared in proportion to each worker's productivity. Diminishing crew returns
therefore also reduce per-worker XP. Scavenging uses the ordinary 1 XP/hour rate;
this is the prototype interpretation of the common productive-work rule.
Completion rounding never awards work beyond the project's remaining amount.

XP credits are persisted privately in game events between fixed simulated-minute
boundaries shared with recovery. At each boundary XP is applied, thresholds are
checked, and each newly reached level is recorded once in citizen_level_history.
The final season boundary applies any remaining earned credit. The following
interval uses the new level and reallocated housing. Browser refresh frequency
cannot accelerate progression. Pause/resume retains partial credit and shifts
the shared clock; suspended and finished settlements do not progress.

Maximum HP and level-based productivity increase through the existing workbook
formulas. Leveling preserves absolute current HP: it grants no free healing.
Consequently a newly leveled citizen may need natural recovery to fill the new
maximum before receiving the full productivity benefit. Housing priority continues
to use Level, then cumulative XP, then seniority.

The roster shows cumulative XP beneath each level. XP/level changes trigger the
existing live refresh. All XP, health, resources, work and history changes share
one transaction. Failed actions roll back without gaining XP or rerolling loot.

Combat and repair XP remain inactive until those systems are implemented. No
retroactive XP is awarded for work performed before enabling this increment.

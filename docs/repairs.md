> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

Current maintenance and voluntary building removal are documented in [Maintenance guide](maintenance.md). Earlier deferred notes below describe the previous increment.

# Building repairs

> This guide records its original increment. Later implemented features and current limitations are listed in [the consistency review](review.md).

Enable building repairs explicitly to activate prototype configuration v8. It
also enables earlier economy, housing, healing and XP features, preserving saved
resources, health, assignments, loot and construction progress. Source documents,
previous configurations and the SQLite schema remain unchanged.

The user authorized these configurable prototype values because repair costs and
rates are TBD in the GDD and absent from the workbook:
- 20 HP/hour per normally productive repair worker, with the existing construction
  crew diminishing returns and citizen productivity modifiers.
- Material cost: 50% of cumulative construction/upgrade material cost through the
  current level, multiplied by missing HP / maximum HP. Fractional materials are
  retained. Full costs are paid at project start; removing workers does not refund.
- 1 HP/hour free Town Hall regeneration while a living Administrator is assigned,
  including during upgrades. Regeneration is a flat rate, not another worker job.

Select a damaged permanent building, choose Start repairs, then assign idle repair
workers. Remove workers with Release; unstaffed projects retain progress. Crews
are released on completion. Repair work earns the workbook's construction/repair
XP, shared according to actual crew work; free regeneration awards no repair XP.

Production and current housing/storage remain available during manual repair.
Their condition-dependent effectiveness increases as HP returns. Repairs require
safe Oxygen coverage, with the existing Town Hall work exception. Destroyed
buildings, construction sites, upgrading buildings and nonrepairable tents are
ineligible. Repairs and upgrades cannot overlap. New repair projects are blocked
in the final three-hour settlement window; already funded repair work may continue.

Building HP is updated on the existing simulated-minute grid, or at repair
completion/season end. Intermediate request progress is saved without changing
production mid-minute, keeping arbitrary refreshes equivalent to offline catch-up.
Town Hall regeneration and manual repair add together and stop at maximum HP.
Unapplied regeneration credit is settled before starting manual Town Hall repair.
Pause freezes work and retains partial credit; suspended and finished settlements
remain frozen. All spending, HP, work, XP and history updates share one transaction.

The initial Town Hall has no construction material cost in the workbook, so its
level-1 manual repairs cost no materials but still require crew time. Higher
Town Hall levels include their cumulative upgrade costs.

Damage remains an existing supported state; this increment adds no combat,
random injuries, player damage controls, repair drones, cancellation or demolition.

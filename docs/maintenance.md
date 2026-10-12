> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# Drone maintenance and building management

Choose **Enable maintenance and building management**. Configuration v11 extends
the existing economy, support and defense catalog. Earlier configurations and
source documents stay unchanged; supply consequences remain a separate opt-in.

## Drone servicing

Select a damaged surviving drone and a staffed, functioning Engineering Workshop.
Each workshop services one drone at a time at 10 HP/hour. Materials are paid once:
25% of that drone's manufacture cost multiplied by its missing-health fraction.
Trade reservations cannot be spent. Full-health, destroyed, deployed and foreign
units are rejected. Its original home/storage slot remains reserved, and the
serviced drone cannot attack or provide defense while its status is repairing.

Workshop outages or loss of effective staffing pause work. Restoring operation
resumes saved progress without paying again. Completion returns the unit to
available at full HP. Time pauses and season-end boundaries apply; unfinished
service is cancelled at season end, retaining earned HP and releasing the unit.
Paid inputs are not refunded at season end. No resurrection or passive drone
healing is introduced. Workshop service operates on stored units without moving
their home or adding travel in this prototype.

## Repair Drones

A living available Repair Drone needs a staffed, functioning home Engineering
Workshop. Choose a damaged permanent building for a manual order, or select
automatic repairs. Drones contribute 10 HP/hour each at full health, scaled by
their own remaining HP. This adds to citizen crew repairs and Town Hall
regeneration; it grants no citizen XP and does not receive the Engineering
Workshop's separate crew bonus. Repair Drones need no human crew at the target;
they can repair buildings beyond human Oxygen coverage.

Manual selection starts the normal paid building-repair project or joins an
existing one without another charge. Its order ends after that project. Automatic
mode selects the lowest condition percentage, then building ID; it keeps that
target until finished and then selects the next eligible, affordable project.
Automatic mode may spend the ordinary building-repair cost. It never creates debt,
spends trade reservations or starts a new project during the final three hours.
Existing funded work can finish during that window. Multiple drones may join the
same paid project without duplicate spending. Tents, destroyed structures,
construction sites and buildings being upgraded are excluded.

Stopping a drone order stops its contribution; paid work remains available for
citizen crews or other drones. Servicing a Repair Drone also stops its order.
Orders and progress persist across restarts. Structural combat against these
support units remains part of the future structural-combat increment.

The user approved these configurable drone rates and costs on 2026-10-08 because
the GDD/workbook do not define them. A single simultaneous service per workshop
keeps this first service workflow bounded and simple.

## Cancellation and demolition

Workbook Scavenging Settings govern material returns:

- Cancelling construction or an upgrade returns `90% - 65% × progress` of its
  committed Scrap, Metal and Electronics. Progress is settled to the command time.
- Cancelling initial construction releases its builders and frees the footprint.
  Cancelling an upgrade releases its builders but retains the prior level, HP,
  production assignments and footprint. Completed work cannot be cancelled.
- Voluntary demolition recovers 40% of invested Scrap, 35% of Metal and 25% of
  Electronics from completed construction/upgrade history. Legacy/pre-seeded
  structures without that history use the corresponding completed level costs.
  No recovery multiplier from scavenging is applied.
- Recoveries fit into free shared material storage proportionally. Overflow is
  discarded, and this is stated beside each action before submission. Existing
  resources and trade reservations are never removed to make room.

Demolition requires the permanent-demolition checkbox in the browser. The Town
Hall is protected. Finish/cancel active projects first. Buildings with surviving
stored/deployed/repairing military assets, stored munitions, funded destination
reservations, factory batches or drone service jobs cannot be demolished.
Resource storage or utility providers cannot be demolished when their removal
would reduce usable storage below currently held resources or lose protected
Cold Storage food. Use or trade supplies first.

Demolition ends local citizen assignments, rebalances housing and utility effects,
and frees the map footprint. Historical building/job/event rows remain for audit;
repeat submissions do not pay another recovery. Voluntary removal does not create
a combat derelict or trigger an attack shield. Ruined-building salvage, hostile
structural damage and rebuilding from ruins remain deferred.

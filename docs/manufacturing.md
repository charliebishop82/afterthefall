> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

Current maintenance and voluntary building removal are documented in [Maintenance guide](maintenance.md). Earlier deferred notes below describe the previous increment.

# Military production

Choose **Enable military production**. Configuration v9 adds all workbook levels
for Drone Factory, Munitions Factory, Offensive Drone Hangar, Air Defense Bay,
Ground Defense Bay, Engineering Workshop, Missile Silo and Interceptor Battery.
The existing placement, construction, upgrade, repair and staffing controls apply.
Factory production and most military storage unlock at Town Hall 3; the Engineering
Workshop unlocks at Town Hall 2. Costs, HP, footprints, crew limits, utilities,
capacity and factory upgrade speed bonuses come from the current workbook.

The military panel supports all six Manufactured Units rows:

| Unit | Factory | Compatible home |
| --- | --- | --- |
| Offensive Drone | Drone Factory | Offensive Drone Hangar |
| Air Defense Drone | Drone Factory | Air Defense Bay |
| Ground Defense Drone | Drone Factory | Ground Defense Bay |
| Repair Drone | Drone Factory | Engineering Workshop |
| Missile | Munitions Factory | Missile Silo |
| Interceptor | Munitions Factory | Interceptor Battery |

Queue a fixed batch of 1–100 units or choose repeated batches. Quantities are a
prototype form limit; they are not a unit balance value. Batches run in submission
order with one current batch per factory. Production time is the workbook's base
time divided by summed effective worker productivity, building condition, and the
factory's 0% / 15% / 30% speed bonus. Factory crews have no construction diminishing
returns. Productive factory workers earn ordinary work XP; idle or stalled factories
award none.

Each unit starts only when the factory has effective workers, safe required utility
coverage and capacity, enough available Metal/Electronics, and a functioning compatible
storage slot. Material arriving continuously can start production at its input boundary
during offline catch-up. Inputs are deducted per unit when work begins, not for the
whole unfunded queue. Trade reservations are respected. The destination slot is
reserved by the funded job, preventing two factories from promising the same last slot.
Existing stored or deployed drones continue to occupy their assigned home slots.

Factories automatically pause without losing funded progress when a worker, required
utility or compatible slot becomes unavailable. Equipment is never produced and
discarded for lack of storage. Capacity scales with storage HP and rounds down.
Storage upgrades retain existing equipment, but delivery waits for the building
to finish upgrading and operate again. Factories can be repaired while producing;
factory upgrades require the active funded project to finish first.

Completed drones are individual persistent military_units rows with workbook HP and
their home building; missiles/interceptors are quantities in military_inventory.
Reloads cannot duplicate output or spending. Stop repeating finishes the current batch
without starting another. Unfunded queued/remainder work may be cancelled; funded
unit cancellation/refund is deferred. At season end, unfinished work is cancelled
without producing equipment. Paid materials are not returned. New batches close
during the final three hours; repeat batches do not begin another cycle in that window.

Support/defense configuration v10 now enables offensive drone resource raids and
automatic air/ground drone defense. Engineering Workshop support bonuses are active.
See [Drone combat](drones.md) and [Support](support.md) for current rules.
Missile/interceptor use, repair-drone actions, turret combat and structural damage
remain deferred. Source documents and previous configurations remain unchanged.

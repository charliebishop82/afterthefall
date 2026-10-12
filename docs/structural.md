> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# Structural combat and ruined-building recovery

Enable **Structural combat and recovery** from the settlement page. This activates
`prototype_v12` for the shared season (or the local save). It retains all earlier
features, resources, identities and settings. It does not change the schema or
rewrite the source workbook. Citizen consequences are a separate opt-in step.

## Play loop

- Manufacture missiles and interceptors in the Munitions Factory. Store missiles
  in Missile Silos and interceptors in Interceptor Batteries.
- In account mode, declare war and wait one hour. Send citizens, offensive drones,
  missiles, or a mixed package. Every package takes one hour and one daily allowance.
- Choose a resource objective for loot, or **Infrastructure** for citizen building
  damage instead of loot. Missile-only packages have no loot-carrying capacity.
- Automated Turrets unlock at Town Hall 2; Anti-Air Turrets at Town Hall 3. All
  construction costs, upgrades, HP, power demands, radii and strengths come from
  the latest workbook. They need power and no ammunition or staff.
- A damaged permanent building can be repaired. At zero HP it becomes a private
  ruin: assign scavengers under **Destroyed buildings**, recover salvage gradually,
  then build normally on the cleared footprint. Tents disappear without salvage.

## Resolution and approved prototype interpretations

Missiles resolve before air combat, ground combat, and raid damage/loot. Each
incoming missile uses one available interceptor from a functioning battery if
possible: level 1/2/3 success is 55%/65%/75%. Both ammunition types are finite.
Missiles target random surviving buildings for 300 HP, with 90 HP splash within
one tile of the footprint. Anti-Air Turrets do not intercept missiles.

Turrets defend targets within their footprint-distance radius in the corresponding
air or citizen/ground phase. Resource packages approach the Town Hall; infrastructure
packages approach a randomly selected surviving building. Condition scales strength.
Workers at that target participate in its ground defense; other workers stay at work.

Successful infrastructure citizen raids apply 20% of surviving citizen strength as
building damage. Surviving offensive drones apply 35% of their strength after combat.
Occupants lose maximum citizen HP multiplied by the building's actual HP loss divided
by its maximum HP. Occupants include workers at the building and allocated residents.
Private reports retain building HP changes, occupant injuries and interception rolls.
Combat death morale uses the existing per-attack cap, including chain explosions.

A destroyed munitions store detonates for 180 HP per stored round, falling by 50%
per extra tile of footprint distance. Each store explodes only once in a chain.
Launched missiles have already left the store and cannot explode there. Destruction
cancels associated work and destroys stored military assets and funded units. Drones already away continue their mission after their home is destroyed, and the
owner receives a warning to rebuild compatible storage. Combat, structural damage
and earned rewards resolve before return storage is checked. Returning drones use
free compatible replacement slots; without a slot they are destroyed on return,
without reversing earned rewards. Stored drones are still destroyed with their home. Recalled missiles return to a surviving original home;
if it has been destroyed, that reserved ammunition is lost and recorded as consumed.

Destruction salvage is 35% of invested Scrap, 30% of Metal and 20% of Electronics.
Actual paid construction/upgrade history is used; legacy buildings fall back to their
catalog costs. An unfinished project's investment and clearing time scale with actual
progress. The user approved clearing work equal to completed construction/upgrade time,
using the existing diminishing scavenger speeds. Salvage Depot speed/yield bonuses
apply. Incoming salvage above free shared material storage is discarded. Clearing is
progressive and repeat requests cannot duplicate recovery. New projects close in the
final three hours, while existing work may continue.

The Town Hall cannot be destroyed: hostile damage stops at 25% of its current
level's maximum HP. Repeated hits at that floor cause no further occupant injury.
Older saves already below the floor are not healed by attacks; an administrator
can correct them while play is frozen. The Hall retains at least level-1 base utility output
and its utility zones. Hostile damage leaving it as the only surviving building (all other buildings
and construction/upgrade sites must be destroyed)
starts 24 hours of rebuilding protection and recalls later inbound attacks, refunding
their allowances. A shield can trigger again only after three functional non-Hall
buildings have recovered since the previous shield. Voluntary demolition does not
trigger it. Launching an attack ends the attacker's protection as before.

## Scope

Citizen capture, allied defense, Vault/Credit raids and banking remain
separate increments. All previous configuration files and synced sources stay unchanged.

Public markets, basic diplomacy and player communication are available in account mode; see social.md.

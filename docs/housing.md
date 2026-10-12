> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# Housing and scavenged survivors

> This guide records its original increment. Later implemented features and current limitations are listed in [the consistency review](review.md).

Prototype configuration v5 enables this increment explicitly through **Enable
housing and survivors**, or when a housing building is first placed successfully.
Older saves keep their previous rules until that action. No SQLite schema change
is needed. Production and the Warehouse-at-Town-Hall-1 exception are retained.

## Housing

At the user's request, each workbook housing type is independently buildable:
Pup Tent, Upgraded Tent, Shack, House, and Apartment Block. Each uses its listed
footprint, Town Hall unlock, costs, construction times, HP, capacities, Oxygen
demands, and upgrade levels. Building types do not convert into other types.
Consequently this increment uses fixed workbook footprints rather than the GDD's
alternative footprint-expanding cross-type housing chains. Source files stay
unchanged. The repeated capacities in House/Apartment levels are intentional.

Usable capacity rounds down after scaling by building condition. Construction
adds no capacity; upgrades retain the current completed level's capacity.
Housing requires at least 75% Oxygen coverage and its configured Oxygen supply.
Housing takes priority ahead of Water/Food and industry during a shortage.
Optional Electricity does not remove housing capacity. Town Hall housing also
requires an operating Oxygen zone and scales with its HP.

Housing is derived automatically, not manually assigned or stored as an
authoritative capacity. Citizens receive the best available housing in order of
Level, XP, current settlement seniority, then citizen ID to resolve exact ties.
Quality is ordered by the workbook's housing morale bonus. Oxygen loss evacuates
unusable housing; restored Oxygen makes it available again.

Becoming homeless applies the workbook's immediate -10 morale penalty once per
episode and records `homeless_since` and a morale event. Rehousing clears that
timestamp. It does not undo the penalty or repeatedly subtract morale on reads.
Housing comfort bonuses, ongoing morale adjustment, homelessness health loss,
births, daily population-floor recovery, combat, and damage rules for tents are
deferred. The UI identifies these inactive effects.

## Survivor discovery

Each uncleared ruin receives one private persisted survivor opportunity when v5
is enabled. Cleared ruins never award survivors retroactively. Ordinary material
loot and existing scavenging progress are retained. An interrupted/reloaded job
does not reroll the opportunity or identity.

The Derelicts sheet provides the base probability (1–8%, depending on ruin type).
At discovery, subtract 0.25 percentage points for each living citizen above six,
with a zero floor. The Scavenging sheet supplies Level 1, 35 morale and 75% of
maximum HP. A discovered survivor immediately joins, with generated name and sex,
membership and level history, and no work assignment. They can be assigned using
the existing controls. Food/Water consumption increases immediately. They join
even when housing is full; normal homelessness rules apply.

Prototype choices where the documents leave details open: one opportunity per
ruin, uniform discovery between 15% and 85% of the remaining work, zero minimum
chance after population decay, and a small local identity-name pool. These are
versioned settings/implementation choices, not edits to the balance workbook.
The elapsed-time engine settles at the discovery boundary before using the new
population's rates. Discovery, ordinary loot, progress, and citizen creation are
one atomic transaction. Private outcomes are excluded from HTML/API responses.

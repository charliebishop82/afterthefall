# Military equipment market

The Public market includes finished drones, missiles and interceptors. Shared
stock starts empty and grows when players sell. Bank-backed sales pay immediately;
purchases consume pooled stock. There are no individual listings or delivery delay.
The existing seller fee applies (8%, strongest functioning Trading Post reduction,
2% minimum, rounded upward). Trade agreements do not change these prices.

Each settlement also has a separate paid daily reserve. It resets at midnight UTC
without accumulating. Reserve purchases neither consume nor replenish shared stock;
selling purchased equipment adds to shared stock without restoring the allowance.

| Equipment | Buy / reserve price | Sell price before fee | Daily quantity |
| --- | ---: | ---: | ---: |
| Offensive Drone | 297 | 99 | 1 |
| Air Defense Drone | 301 | 100 | 1 |
| Ground Defense Drone | 238 | 79 | 1 |
| Repair Drone | 243 | 81 | 1 |
| Missile | 360 | 120 | 1 |
| Interceptor | 243 | 81 | 2 |

Prices are configurable in config/equipment_market.json. Initial purchase prices
are 150% of manufacturing Metal and Electronics valued at the resource market's
buy prices (rounded down); sale prices are 50% before fees. Manufacturing itself
retains its existing costs, workers, duration, factories and unlocks.

## Starter storage

Current prototype_v13 settlements can build six Small counterparts of the existing
Offensive Drone Hangar, Air Defense Bay, Ground Defense Bay, Engineering Workshop,
Missile Silo and Interceptor Battery at Town Hall 1. Each accepts its matching type.

Each is one tile, costs 25 Scrap and 10 Metal, takes ten builder-minutes, and has
150 HP. Each drone home holds one drone; each ammunition home holds two rounds.
These have one level; larger buildings retain their existing unlocks and upgrades.
No starter store needs Electricity. Only the Small Engineering Workshop needs
one operating worker and Oxygen (one capacity); it has no construction bonus.
Construction and exposed-worker safety still follow the existing rules.

Buying requires sufficient unreserved Credits and operational compatible storage.
Deployed units, ammunition reservations and paid manufacturing jobs keep their
normal storage reservations. Buyers do not need a factory. Purchased units enter
the existing combat, repair, defense and return-home systems at normal full health.
Capacity still falls with building condition; purchases cannot overfill it.

Only full-health available drones with no unfinished targeted job can be sold.
Munition sales use only stored uncommitted quantity. The seller's drone ID is
retired using the existing terminal unit status, retaining historical references;
the equipment trade event records the sale, not a combat loss. A later buyer gets
a new full-health unit ID. Market stock contains types and counts, not individual
drone histories. Sales cannot duplicate units or produce profitable resale loops.

## Saves, logs and checks

No save reset is required. New market tables are created additively inside the
first successful equipment transaction. Read-only displays work before those
tables exist. Every trade has quantity, price, seller fee, Credits, timestamp and
unit IDs in its audit record and game event, plus the existing paired Bank ledger
entries, player notification and HTTP request logging. All writes roll back
together on failure. The existing Update panels signal includes stock changes
and daily allowance resets. The admin suite can inspect the usual event/log views.

Restart the game and admin processes after installing; restart bots if running.
Use the same database path. Bots now use equipment purchases/sales, starter storage, scaled military goals
and workshop maintenance; see bot-equipment.md for personality and audit details.
The in-game HTML guide is updated; the previously published PDF is not regenerated.

Tests in tests/test_equipment_market.py are automatically discovered by the
parallel runner. They cover transactions, capacity, readiness, reservations,
invalid requests, daily reset, personal allowances, ledger rollback and form
routing. Tests were not executed, following the owner's standing instruction.

Run just this module when desired:

    python -X utf8 -m unittest tests.test_equipment_market

Or the complete Python suite:

    python -X utf8 run_tests_parallel.py --workers 2

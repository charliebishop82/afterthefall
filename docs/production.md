> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

> **11 October economy update:** expansion-enabled games now include renewable
> Scrap from staffed Salvage Depots. See [the building/economy review](building-economy-review-2026-10-11.md).

# Civilian production and upgrades

> This guide records its original increment. Later implemented features and current limitations are listed in [the consistency review](review.md).

This increment activates the civilian economy: Food, Water, Electricity, Oxygen,
material conversion, storage, and scavenging. Military manufacturing remains
outside the agreed scope.

## Catalog

All workbook levels are implemented for these 20 building types:

- Town Hall; Garden; Greenhouse; Hydroponics Facility.
- Rain Collector; Well/Pump; Purification Plant.
- Oxygen Garden; Oxygen Generator; Industrial Oxygen Plant.
- Solar Array; Wind Turbine; Generator Plant.
- Root Cellar; Cold Storage; Water Tank; Scrap Yard; Warehouse.
- Recycler; Electronics Fabricator.

Construction, upgrades, incremental spending, worker release, and offline progress
use the previous increment's work model. Passive buildings need builders during
construction but no production workers afterward. Staffed workplaces respect
minimum crew sizes and level-specific maximum slots. Upgrade panels show the
next level's output/capacity, costs and one-builder duration. No maximum levels
or upgrades were invented for single-level buildings.

`config/prototype_v4.json` holds the workbook values. The one approved balance
exception is Warehouse unlock at Town Hall level 1 (workbook: level 2). The
workbook also has a level-1 Scrap Yard, which could otherwise provide the storage
needed for the first Town Hall upgrade. The earlier proposed deadlock was an
incomplete catalog reading; the user chose to retain earlier Warehouse access
after that correction. Source files and older configurations are unchanged.

## Playing the economy

Choose **Enable civilian production** once. The existing save and paused clock
are retained. This enables the catalog and adds uncleared derelicts only on free
tiles. Choosing a new civilian building also enables the economy automatically;
invalid commands roll back the entire operation.

A useful opening is a Garden, two Rain Collectors, and material storage. Assign
builders, start time, then assign a Food worker when the Garden completes. Rain
Collectors produce continuously without workers or utilities. Food and Water
can then support scavenging and later development.

Open a nearby derelict in the scavenging panel and assign an idle citizen.
Workers recover ordinary supplies gradually, with the workbook's crew speed and
loot ranges. Completion frees the footprint and releases the crew. Pausing time
or removing all scavengers preserves progress. The private loot outcome is stored
once; reloads and repeated commands cannot reroll or duplicate it. The browser
never receives the nonce or unrecovered loot totals. Storage overflow is discarded.

Scavenging provides Scrap, Metal and Electronics. The Recycler converts Scrap
into Metal; the Electronics Fabricator consumes both Scrap and Metal. Exact
per-worker input/output values come from their workbook levels. Converters stop
at input depletion without pausing the season or granting free output. Material
arriving continuously from scavenging/other converters can feed a plant directly.
Scrap, Metal and Electronics share one capacity; production cannot create extra
overflow. Existing excess in an older save is preserved while it is used down.

## Storage-aware throughput

Continuous Food and Water production slows when output storage is full. It can
still replace supplies consumed during the interval. Producers share the useful
throughput proportionally; their XP follows that work fraction. Near-full storage
permits only the work that fits, including consumption during the interval.

Converters may continue in a full shared material pool when their inputs free
space for their outputs. Reserved inputs cannot be spent. If incoming salvage
would crowd out converter products, the stored salvage is limited and converter
input availability is recalculated. Inputs are never spent on discarded converter
output. Scavenging overflow is still lost; clearing work and its XP still count.

## Utilities and storage

Electricity and Oxygen require both geometric coverage and sufficient generated
capacity. Footprint tile centers use the approved 50% union rule. Every
functioning provider adds capacity and its own footprint-distance zone. Zones
overlap without multiplying radius or counting a tile twice. Only sources that
can actually start contribute coverage: disconnected generator/Oxygen dependency
cycles cannot power themselves.

Providers are resolved before ordinary consumers. Water has priority over Food,
then Industry, then storage. Within a tier older completed buildings take
capacity first. Staff remain assigned during utility shortages and resume when
conditions recover. Plants respect minimum staffing and HP shutdown at 25%;
output above that scales with HP and worker productivity. Passive sources have
fixed continuous output; no weather, fuel or accumulated power/Oxygen resources.
Staffed source output follows the existing per-worker interpretation of the
workbook production values.

Storage scales with completed building condition and adds nothing while a new
site is unfinished. Cold Storage has 25% usable capacity while unpowered, per
the workbook Utilities correction. Excess Food is retained but inaccessible.
A saved storage-lock event preserves that inaccessible portion across requests;
consumption cannot gradually draw it out while power remains absent. Restoring
power releases it. The shortage forecast uses accessible Food.

Season pause freezes all work and resource flow. Suspended settlements and
finished seasons remain frozen. New projects close in the final three hours.
Food/Water depletion retains the prototype's automatic pause before health effects.

## Prototype settings and deferred systems

The common prototype map has 64 derelicts, including four initially covered ruins;
map density is a configurable prototype choice rather than a workbook balance
value. Layout uses a reproducible map seed and avoids existing buildings. Private
loot uses a server-side random nonce and is persisted immediately. Tests patch
the nonce with a fixed seed and use controlled clocks/disposable databases.

Construction diminishing returns, tile-center coverage, health productivity and
reduced Town Hall output during upgrades retain the prior documented prototype
interpretations. See food.md. The SQLite schema remains version 1; existing
tables store jobs, assignments, derelicts, resources and history.

Survivor discovery, support-building bonuses, citizen progression/exposure,
repairs, cancellation/demolition controls, multiplayer, markets and combat remain
inactive. Scavenging adds ordinary loot only; it does not yet add citizens or
roll survivor events. These boundaries are visible prototype scope, not changes
to the V1 design or balance authorities.

Run `python run_tests.py` to execute new economy tests and all earlier regressions.

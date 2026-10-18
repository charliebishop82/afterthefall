# Targeted redundancy review and suite tiers

All 898 pre-existing test methods were retained, with exactly unchanged
method bodies. Three selection/reporting tests were added (901 defined
Python test methods total). No tests were executed during this change.

The everyday quick suite explicitly selects 14 Python modules. Optional
UI discovery still adds all UI modules to either suite. Full remains the default
and still discovers every new test automatically. Quick summaries identify their
scope and record excluded modules, rather than counting them as passed or skipped.

## Slow-module coverage decisions

| Apparent overlap | Decision and reason |
| --- | --- |
| Current whole-catalogue upgrades vs older civilian construction sweeps | Keep both: current direct job completion checks costs, preserved HP and idempotence; legacy sweeps exercise real elapsed simulation and supported configurations. |
| Housing catalogue vs generic upgrades | Keep: checks housing allocation/capacity and independent housing types, beyond generic construction. |
| Factory construction vs catalogue upgrades | Keep: factory test covers construction, elapsed processing and production-version activation. |
| Drone and missile combat | Keep: separate phases, ammunition consumption/interception, loot, injuries and return-home rules. |
| Servicing, building repair and automatic Repair Drones | Keep: different spending, target, pause and double-payment boundaries. |
| Offline vs incremental comparisons in several systems | Keep: shared timing pattern but different boundary side effects and saved results. |
| Garden and catalogue configuration-only checks using full worlds | Optimize setup: create worlds lazily, without changing assertions or test identity. |

No behavioral test was proven redundant enough to delete safely. This increment
reduces routine execution through explicit scope, not weaker assertions or hidden
skips. Further consolidation should follow current measured durations and retain
an explicit coverage replacement for each removed case.

The quick set includes:

- test_database.py
- test_accounts.py
- test_flask_playtest.py
- test_request_clock_order.py
- test_production_storage.py
- test_market_pool.py
- test_market_reserve.py
- test_equipment_market.py
- test_bot_market.py
- test_bot_combat.py
- test_parallel_runner.py
- test_background_progress.py
- test_live_values.py
- test_resource_alerts.py

Use the quick suite for minor edits plus focused feature tests where appropriate.
Use the full suite after shared-rule changes or before a playtest release. Neither
suite has been run by Codex, and no speedup or passing result is claimed.

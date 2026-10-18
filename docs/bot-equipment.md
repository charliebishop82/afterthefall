# Equipment-aware bots

Policy version: equipment-market-v6. Bots submit the same /market, /buildings,
/manufacturing and /conflict forms as players. There are no grants, privileged
stock, altered prices, extra storage or exceptions to normal combat rules.

The ordinary player resource response now includes public equipment prices and
shared stock plus the caller's own remaining daily allowance, operational free
slots and saleable quantity. Other players' private equipment or allowances are
not exposed. The runner records this observation and its seeded decisions.

## Behavior

- Existing Administrator, essential production and emergency supply priorities
  remain. Equipment purchases are blocked during Food/Water deficits or empty
  stocks. Bots retain a Credit cushion (100 aggressive/defensive, 150 balanced,
  200 builder/scavenger) plus a six-hour supply-purchasing buffer when needed.
- Bots buy one desired unit per step, choosing an affordable source. Shared stock
  wins on equal prices; the personal daily reserve provides a fallback. Exhausted
  allowances, lack of stock, Credit reservations and operational capacity are
  respected. No attempt is made to buy beyond the observed free slots.
- A staffed compatible factory is preferred when manufacturing is affordable.
  Bots can buy missing manufacturing inputs to resume an unpaid paused batch.
  Deployed units, committed ammunition and unfinished manufacturing quantities
  count toward targets so the bot does not order duplicate replacements.
- Small Town Hall 1 homes are built when needed. Their workshop is staffed.
  Bots grow into the larger existing homes and upgrade full upgradeable homes
  as targets grow. Missing construction/upgrade materials can be purchased
  through the ordinary resource market. Starter buildings remain level 1.
- Healthy idle equipment above the personality's target is sold one unit at a
  time. Under urgent supply pressure and fewer than 50 unreserved Credits, bots
  may sell toward a one-unit floor for desired types; unwanted types have a zero
  floor. Deployed, damaged, repairing, job-reserved or actively ordered Repair
  Drones cannot be sold. Equipment under automatic/manual repair orders is now
  excluded from sale for human players as well, matching the idle-only rule.
- Bots staff workshops, pay for drone servicing when affordable, and enable
  automatic paid building repairs for healthy Repair Drones with functioning
  homes. Purchased military hardware uses the existing raid/defense logic.

## Personality targets

These base targets multiply by Town Hall level, capped at level 3. A shuffled,
seeded order breaks ties; larger targets take priority. The existing random
military/expedition/economy selection preserves personality variation.

| Personality | Offensive | Air defense | Ground defense | Repair | Missiles | Interceptors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Aggressive | 3 | 2 | 2 | 1 | 3 | 2 |
| Defensive | 0 | 3 | 3 | 1 | 0 | 3 |
| Balanced | 2 | 2 | 2 | 1 | 2 | 2 |
| Builder | 0 | 1 | 1 | 2 | 0 | 1 |
| Scavenger | 1 | 1 | 1 | 1 | 0 | 1 |

Targets are goals, not entitlements. Affordability, construction, worker and
capacity rules may delay growth. Bots do not create equipment just to resell it:
manufacturing and purchasing stop at the same target used for surplus sales.

## Inspection and tests

Existing admin bot traces contain the market observation, chosen source, goals,
budget/capacity reason, submitted action, HTTP outcome/request ID and after-state.
Manufacturing observations include only paid/remaining/produced/home fields;
private scavenging inputs and random loot remain excluded. HTML rejection pages
are reduced to their visible alert rather than copying forms or CSRF tokens.

Restart both the player server and bot runner with the same database; restart
the admin suite to refresh imported code. Existing bots retain their identities,
personalities and enabled/paused settings. No save reset or bot recreation is
required.

New tests in tests/test_bot_equipment.py are automatically discovered by the
parallel runner. The old policy-version audit expectation changes from
expeditions-v5 to equipment-market-v6 intentionally. No tests were executed.

    python -X utf8 -m unittest tests.test_bot_equipment tests.test_equipment_market

    python -X utf8 run_tests_parallel.py --workers 2

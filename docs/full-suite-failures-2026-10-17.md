# Full-suite failure corrections — October 17, 2026

Baseline: test-results/parallel-20261018T004147686737Z/summary.json,
935 executed tests, 102 completed modules, nine failures and no errors.
The following changes address every reported failure without changing gameplay
rules, Host/CSRF security, simulation budgets or the player's save.

| Failure | Cause and correction |
| --- | --- |
| Building catalogue count | Six approved starter storage buildings expanded 42 types to 48. The test now requires 48 plus the exact six starter IDs and their level-1 unlock/max-level rules. |
| Citizen Oxygen evacuation | A staffed Garden now supplies its own Oxygen. The outage fixture uses a Recycler, which consumes rather than supplies Oxygen. A separate case preserves the Garden self-coverage behavior explicitly. |
| One-interval catch-up | Quiet bulk processing can legitimately finish 20 minutes in one interval. The resumability fixture now has an injured citizen, guaranteeing real detailed healing boundaries; it retains partial progress and all final state comparisons. A separate quiet-world case requires one-interval completion. |
| Player-guide reference | The HTML had a general starter-storage explanation but lacked six individual catalogue entries and current metadata. Added all six references with costs, capacity, work, staffing and utilities; refreshed 48-type/114-level counts and configuration hashes. |
| Greenhouse power outage | Destroying the turbines beside Town Hall leaves Town Hall Electricity available. The fixture now places a staffed Greenhouse outside Town Hall utility coverage and gives it a local turbine, then removes all turbines. It still requires both outputs to stop. |
| Public scores privacy | Public rankings intentionally include processed_at so players can assess saved snapshot freshness. The strict allowed-field set now includes that timestamp and checks its integer type; no private loan data is allowed. |
| Three catch-up HTTP failures | The client used default localhost without port, rejected by the real Host allowlist before reaching the routes. Requests and cookies now consistently use 127.0.0.1:8767. Added explicit disallowed-Host and invalid-CSRF cases so security remains enforced. |

The HTML manifest identifies the HTML update separately from the older PDF
edition. The PDF remains the previously published artifact; it was not rebuilt.
The historical tools/build_player_guide.py content source is not used to overwrite
the subsequently maintained HTML in this change.

All existing test methods are retained. Four regression cases were added.
Validation performed: source inspection, static Python parsing, JSON validation,
and checking that every current building type has a catalogue reference in HTML.
No tests, services or bots were run. A passing result remains unconfirmed until
the owner reruns the tests.

For just the affected modules, from the activated Conda project terminal:

    python -X utf8 -m unittest discover -s tests -p test_building_catalogue.py
    python -X utf8 -m unittest discover -s tests -p test_citizen_consequences.py
    python -X utf8 -m unittest discover -s tests -p test_catchup.py
    python -X utf8 -m unittest discover -s tests -p test_player_guide.py
    python -X utf8 -m unittest discover -s tests -p test_food_oxygen.py
    python -X utf8 -m unittest discover -s tests -p test_expansion_http.py
    python -X utf8 -m unittest discover -s tests -p test_catchup_http.py

Complete regression:

    python -X utf8 run_tests_parallel.py --suite full --workers 2 --include-ui

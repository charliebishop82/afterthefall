# Lean saved-rankings reader — 2026-10-18

expansion_views.scores now delegates to scoring_reader.saved_scores. This is presentation-only: it does not advance any settlement, write data, change formulas, change refresh frequency, or cache rankings across requests.

The reader batches settlement resources, buildings, living citizens, relevant construction/upgrade jobs, military units/inventory, in-flight attacker ammunition, loans and investments. Each table is read for the participating settlements rather than once per player's full gameplay state. Configuration is prepared once per distinct participating season within the call and discarded with the temporary scoring inputs. The scoring code only reads those shared rule dictionaries. Returned rows contain no configuration or private gameplay state.

No assignments, utility allocations, housing/recovery clocks, expedition records or citizen-history decoration are needed for scoring. Existing scoring.totals, ruins.invested and scoring.rank remain unchanged. Completed work/cost history is retained because it affects invested building value. Cancelled/queued/non-build jobs are omitted because the existing formula ignores them. Existing debt/investment filters and in-flight ammunition ownership are preserved. Participant order, ties, names, saved clock timestamps and the prior latest-settlement-per-account selection are retained, including historical views.

The caller's connection, read transaction, row format and account scope are preserved. There is no additional connection when called from the shared resource snapshot. No database schema, journal or durability changes.

Validation: syntax checks only; agent did not execute tests. New tests restore a class baseline and compare every returned field against the previous full-state algorithm. Coverage includes ties/order, actual paid costs, partial construction/upgrades, structural damage, excluded jobs/ruins, living/zero-HP citizens, all loan/investment statuses, damaged/deployed/destroyed drones, committed/consumed/resolved ammunition, subsequent-call freshness and empty seasons. Tests also verify fewer SQL statements, no full-state calls on the new path, unchanged database bytes and preserved connection lifecycle.

Run:

    python -X utf8 -m unittest tests.test_scoring_reader tests.test_saved_rankings tests.test_scoring tests.test_refresh_reuse tests.test_refresh_snapshot

The parallel full suite discovers test_scoring_reader.py automatically. The curated quick suite remains unchanged. After tests pass, restart the game server and admin suite with the existing database. No reset is needed. The bot runner's normal HTTP behavior is unchanged.

The earlier read-only profile showed nine full-state loads and 325 SQL execute calls during one resource payload. This change targets that work; no wall-clock improvement is claimed until the new reader is verified and measured under comparable load. A proposed broader utility cache was not installed because read-only timing comparisons showed it was slower in this presentation workload.

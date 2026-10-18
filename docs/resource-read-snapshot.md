# Shared auxiliary reads during resource refresh — 2026-10-18

Resource payload assembly now shares one explicitly read-only SQLite connection/transaction across ranking rows, revision components, public targets, market data, raid/war timers and operation-result notices. Previously these helpers each opened independent connections. Existing ranking reuse is preserved: one ranking calculation per expanded refresh.

The snapshot starts after pure payload calculations, ends before the response returns, and is never pooled or cached across requests. It does not cover or alter simulation transactions, activity writes, authentication, or the authoritative settlement state already supplied by the caller. Related auxiliary fields now come from the same saved-data snapshot rather than potentially differing commits during response assembly. No interface, gameplay, schema, journal-mode, durability or refresh-interval changes are made.

The read_connection helper opens existing saves with mode=ro, query_only and an explicit read transaction. It closes on all exits. Nested readers borrow the connection without committing or closing it; they restore row_factory in finally so tuple-based revision serialization and named-column readers remain compatible. Standalone helper calls still work and obtain their own read-only snapshot.

Read transactions can temporarily delay SQLite writers in rollback-journal mode. This transaction is confined to response assembly under the existing gameplay gate; no network waits or logging are included. Measure request timings and bot lock contention after restarting rather than assuming a particular speedup.

Validation: source syntax checked only; agent did not run tests. New tests cover complete response equivalence against independent readers, one connection per payload, no database-byte changes, error cleanup, read-only enforcement, row-format restoration, subsequent-request freshness, and snapshot consistency with a concurrent writer in a disposable WAL test database. Production journal settings are untouched. Fixtures restore an existing class baseline; no test uses live game data.

Run from the activated environment in the project directory:

    python -X utf8 -m unittest tests.test_read_queries tests.test_refresh_snapshot tests.test_refresh_reuse

Broader affected regressions are included in the normal full parallel suite (automatic discovery includes both new modules). Existing timer, market, communication and operation-result tests remain unchanged. Curated quick-suite selection is unchanged.

Restart the game server and admin suite to load their updated shared reader modules, retaining the same database. Restart the bot runner too if it is still running the earlier read/pacing version; its normal HTTP protocol and launch command are unchanged. No database reset is required.

# Resource refresh ranking reuse — 2026-10-18

The resource refresh previously calculated saved rankings twice: once for its revision signature and again for its response. Each ranking calculation reads all settlements in the season and calculates their scores.

It now calculates the standings once per refresh, passing those rows into revision generation and returning the same rows in the response. No standings are cached between requests. Ordinary standalone revision calls retain their original calculation path. Loan and investment values are still read when building the revision; their changes are not hidden by ranking reuse.

The interface, ranking formula, saved-standings semantics, request interval, simulation timing and database schema are unchanged. This removes one season-wide ranking pass per expanded resource refresh. Other connection/query consolidation remains future work; no measured wall-clock speed improvement is claimed yet.

New tests use one class baseline restored to independent temporary saves. They compare the complete optimized response against an independent-ranking reference, verify one ranking calculation rather than two, check that a subsequent refresh sees another settlement's changes, preserve financial revision detection, and check that refresh assembly leaves the database bytes unchanged. The full parallel suite automatically discovers the test module; the curated quick suite is unchanged.

Syntax checked only; tests not run by the agent. Run:

    python -X utf8 -m unittest tests.test_refresh_reuse

Restart the game server with its existing command and database after validation. The admin tools and bot runner do not need restarting for this change. Compare existing /api/resources duration and lock-wait metrics under similar player/bot load.

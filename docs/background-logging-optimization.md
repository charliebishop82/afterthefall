# Background reporting optimization — 2026-10-18

The coordinator still selects and commits one normal catch-up batch while holding the shared gameplay gate. Fairness, time sampling, catch-up limits and offline rules are unchanged.

After committing, it releases the gate before writing the batch log or printing progress. These reports describe the captured batch/pending snapshot; player actions may legitimately occur before the report is displayed. A blocked terminal may delay further background reporting, but no longer holds the gameplay gate while doing so.

One rotating file handler is opened lazily and reused by each coordinator. JSON fields, immediate per-record flushing, 5 MB rotation and three backups are retained. A separate logging lock protects handler lifetime. Worker shutdown writes its final record and closes the handler; a timed-out stop does not prematurely close a running worker's sink. No database schema or player interface changes are involved.

Validation: Python syntax checked only; automated tests were not run, following the user's instruction. Restart the game server to load the change. The existing save is retained. Admin tools and bot runner do not need restarting for this increment.

Focused check from the activated Conda environment and project directory:

    python -X utf8 -m unittest tests.test_background tests.test_background_logging

The parallel full suite discovers the new test_background_logging.py automatically. The quick suite selection is unchanged. New focused tests use temporary log files and mocked batches, with no world setup or live-save access. Existing background tests now close their reusable handlers before temporary-directory cleanup on Windows.

Compare request timing and lock-wait measurements during similar play before and after restarting. This change removes avoidable lock holding; its impact depends on logging and terminal latency and is not a claimed simulation speed increase.

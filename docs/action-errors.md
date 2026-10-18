# Rejected player actions

Authenticated gameplay forms that raise a validation error return HTTP 400
with the full settlement interface and an escaped, visible "Action not applied"
message. The error remains in the player request log. Navigation, resources,
map, and controls remain available; the existing browser menu preference still
selects the current game screen.

The error view reads the saved settlement after the failed transaction rolls
back. It does not replay the action, advance simulation again, or renew the
player's offline allowance. Refresh the settlement to obtain a newer view.
Authentication errors and API responses retain their existing handling.

An exposed worker can be automatically evacuated at 25% HP before a submitted
release action is validated. A stale assignment form can therefore correctly
report that the citizen is no longer assigned. This presentation change does
not alter evacuation, injury, assignment, or transaction rules.

Regression cases live in tests/test_flask_playtest.py and are discovered by
run_tests_parallel.py automatically. Run them using the documented test commands.
Tests were added but not run during this change, per the owner's instruction.

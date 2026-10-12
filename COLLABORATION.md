# Development and validation handoff

Default workflow agreed with the project owner:

- Codex edits code, documentation and regression tests, and runs tests only when explicitly requested.
- The owner runs the player/admin servers, manual playtests and full regression
  suite in their activated Conda environment.
- Each change is handed off with the intended behavior, focused results, exact
  test commands and a short manual acceptance checklist.
- A focused pass means ready for owner validation. An increment is fully
  validated only after the complete suite passes and its result is available.
- Earlier tests remain intact; reported failures are investigated and fixed.
- Server start/stop/restart and full-suite execution remain with the owner by
  default. Explicit requests can authorize Codex to handle them.

The full-suite requirement still applies; this workflow assigns its execution to
the owner. No gameplay or test requirements are removed. See RUNNING_THE_GAME.md
for Conda setup, restart commands, test logs and troubleshooting.

## Test execution restriction

Do not run any tests automatically, including focused, unit, integration,
regression, browser automation tests or the full suite. Run tests only when the
owner explicitly asks for them. Writing or updating tests remains part of code
changes. Hand off exact commands and mark unrun checks as pending; do not claim
that an unrun check passed. The full suite still needs to pass before a change is
reported as fully validated, and the owner can run it and provide the result.

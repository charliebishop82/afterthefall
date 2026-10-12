# ChatGPT project context

This directory is a local mirror of the ChatGPT project “Multiplayer Game app multi-platform”.

- Treat every file under `sources/` as read-only reference material.
- Do not edit, rename, move, or delete synced project files.
- These files may be replaced the next time a task is created from this ChatGPT project.


## Project instructions

Build the smallest playable prototype incrementally; keep deferred systems inactive until requested.

Every new feature must include meaningful automated tests for expected behavior,
important boundaries, and rejected actions. Preserve earlier regression tests.
Run `python run_tests.py` before reporting any feature or bug-fix increment complete.
Bug fixes should include a test reproducing the defect where practical.
Do not delete, skip, or weaken old tests just to make new code pass. Update an
expectation only for an explicitly agreed rule change and explain the change.
Use temporary state, controlled clocks, and seeded randomness; never test against
the player's database. Keep nested test folders discoverable with `__init__.py`.
Test public behavior, saved progress, and important feature interactions.
Report actual test results and any blocked checks. See `docs/testing.md`.

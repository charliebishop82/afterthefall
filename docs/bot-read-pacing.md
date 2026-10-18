# Bot reads and pacing — 2026-10-18

The pre-refresh check selects only settlement existence. Full state is still read after the ordinary player refresh for policy decisions and save/server identity checks, and again after an action for audit. Waiting decisions need one full read instead of two; action attempts need two instead of three. Rejected refreshes and unenrolled waits need no full state read. All trace phases, before/after observations, errors, pause checks and unknown-outcome/no-replay protections remain.

The default minimum decision interval is 60 seconds plus 0–60 seconds of separately seeded jitter per bot. Longer controller interval_seconds values are retained as the base. Jitter uses its own local RNG keyed by seed, account and step; policy/game RNG is untouched. The runner pauses five seconds after each turn, including waits/errors, before checking another bot. Existing overdue bots are handled sequentially; missed decisions are not replayed. Use one runner per database.

next_at is persisted during the atomic claim, so scheduling survives restart. Interval timing starts at claim time; slow requests and leases may delay a decision further. Simulation, production and military operations continue normally between decisions. Admin interval displays remain configured base values; startup output and step_started fields scheduled_next_at / decision_delay_seconds record effective pacing.

Idle polling performs a read-only eligibility check without BEGIN IMMEDIATE. Due claims still acquire the write transaction and repeat eligibility selection before updating the lease, preserving duplicate-claim protection.

The usual launch command works unchanged. For slower decisions add:

    --min-interval 120 --jitter 120 --action-gap 10

Allowed values: min-interval >=10, jitter >=0, action-gap 1–3600 seconds. Defaults: 60, 60, 5. Restart only the bot runner; no reset or server/admin restart is required.

Syntax checked only; tests were not run by the agent. New tests use minimal temporary tables and mocked HTTP/clocks with no game-world setup or real sleeps:

    python -X utf8 -m unittest tests.test_bot_pacing tests.test_bot_runtime tests.test_economy_bots tests.test_bot_market_snapshot

The full parallel suite automatically discovers the new module; quick-suite selection is unchanged. Compare decision frequency, audit continuity and request/lock timing under similar load. No measured speedup is claimed yet.

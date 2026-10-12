> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# Account-based local multiplayer foundation

Run `python accounts_app.py` and open http://127.0.0.1:8767. This uses
`database/accounts.db`, separately from the original local `prototype.db`.
The local game remains available at port 8765. Account mode refuses to adopt a
populated local save. No existing settlement or password is silently reassigned.

Create a username and password, then explicitly create a named settlement. Account
creation does not join a season automatically. Usernames are fixed, case-normalized
and unique; passwords require 12–128 characters. The current small prototype uses
the username as the persistent player display name. Login/logout controls are
available on the account interface. There is no email/password-reset service yet.

All account settlements share one active season, Town Hall location and seeded
40×40 layout. Common derelict identities are reused while private loot and survivor
opportunities remain independent. New settlements activate the existing v8 economy,
housing, healing, XP and repairs, with the normal starting package and beginner
protection timestamp. Starting Credits are recorded as Bank transfers, including
negative Bank balance. Season joining remains available until season end.

A request selects its account from the server-validated session, never a submitted
account/settlement ID. A request-scoped context selects owned state for the existing
transactional services. Concurrent request threads keep separate contexts, which
are restored after each request. Foreign building, citizen and derelict IDs are
rejected. Gameplay/API responses expose only the current account's settlement.

Passwords use PBKDF2-HMAC-SHA256, 600,000 iterations and a fresh 16-byte salt.
Raw passwords and raw session tokens are not stored. Random session tokens are
stored as SHA-256 hashes; sessions and CSRF tokens survive server restarts and
expire after 24 hours. Authentication/logout rotate the session and invalidate
its previous token. Cookies are HttpOnly and SameSite=Strict; origin checks and
per-session CSRF tokens protect form changes. Five failed logins temporarily block
that username for 60 seconds. Account deactivation invalidates session access.
The account database adds two runtime tables, auth_sessions and auth_failures;
the original V1 schema creator and older saves remain unchanged.

Players cannot pause/resume shared season time. Ordinary offline time progresses
through the existing catch-up engine. The early prototype safety behavior remains:
supply depletion freezes only the affected settlement using its suspended state,
rather than pausing the whole season. The UI/API report this freeze consistently.
Private trading now replenishes supplies and resumes a shortage freeze when
accessible Food and Water are positive. See docs/trading.md. The current Flask
playtest enables starvation and dehydration rules. Administrative suspension now
freezes saved progress; see [Admin operations](admin-operations.md).

Use separate browser profiles/private windows, or log out and switch accounts,
to test two players. Tabs in the same browser profile share their login cookie.
This server remains bound to localhost for development. Public hosting/TLS,
password recovery, account moderation, scheduled/new seasons and full multiplayer
season scoring and detailed historical archives remain separate work. At season
end, all settlements complete eligible simulation, pending raids return their
citizens, unfinished jobs are cancelled, and all settlements become read-only
archives in one transaction. Supply-frozen settlements retain their frozen state
until archival; final resources are recorded for every settlement.
Private trading is enabled; conflict
now includes basic citizen resource raids; see docs/combat.md.

The current game does not need a background simulation thread: gameplay requests
settle the owning settlement's elapsed time. Trading and citizen raids settle both participants in one transaction before applying
their outcomes; raids resolve at arrival before later catch-up.

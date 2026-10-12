# Admin operations and corrections

Launch `./start_admin.ps1` independently of `./start_game.ps1`, then open
http://127.0.0.1:8768/. Both apps default to `database/playtest.db`; use the same
`-Database` path when selecting a different save. The operator console stays local
even when the player game is exposed through a tunnel. It has its own session
cookie and does not require a settlement. The player app rejects operator writes.

Create the selected operator locally with:

```powershell
& ./.venv/Scripts/python.exe manage.py create-admin admin
```

The command prompts privately for a password and confirmation. If that username
already exists, use `manage.py grant-admin admin` instead. There are no default
passwords or automatic first-user privileges. Log in to the operator console with
that account. Existing admin accounts continue to work.

Registration never grants this role. Every data-changing operation requires
a reason; permanent audit rows contain the administrator, time, target, and before /
after values. The dashboard displays the latest 100 actions; older records remain
in SQLite. Passwords never appear in these records.

## Pause and suspension

**Pause Season** first catches all settlements up to the pause time, then freezes
production, consumption, health, construction, manufacturing, repairs, Bank accrual,
daily rolls, raids and shared proposal / cooldown timers. Gameplay submissions are
blocked; communication and account management remain available. **Resume Season**
preserves partial progress, shifts deadlines, and extends the season end and final
window by the paused duration. Closing the server alone does not pause time.

**Suspend** revokes the player's sessions, freezes their settlement, hides their
market listings and blocks attacks / exchanges with them. Existing raids involving
them are recalled immediately using the normal refund rules. Private offer stock
remains reserved and shared offer / treaty timers wait until participants are
reactivated. Other players continue normally. **Reactivate** excludes suspended
wall time from catch-up; it does not restore revoked sessions. Overlapping player
and season pauses count once. An earlier supply freeze stays in effect.

Past creation, loan opening, treaty acceptance/cancellation and audit timestamps
are preserved. Separate operational offset records preserve treaty cooldowns.
Season completion still closes and archives participants under the existing rules;
full season rollover remains deferred.

Three additive operational tables store player freezes, shared timer holds and
treaty cooldown offsets. No original V1 schema or balance workbook is modified.

## Diagnostics and logs

Diagnostics use a read-only committed SQLite snapshot. They check database
integrity, foreign keys, missing resource rows, stock reserved beyond holdings,
reservations left on closed offers and inconsistent suspension metadata. They also check citizen/building/drone health, catalogue levels and live assignment ownership. Preserved duplicate citizen names are warnings identified by IDs. They
report issues without silently changing values or advancing game time. These are
targeted checks, not proof that every possible gameplay inconsistency is absent.

Logs display up to 100 game events, with exact settlement/type filters and paging before an event ID. A JSON download exports that matching chunk. Authentication remains operator-only; exports do not advance game time. Logs also show the last 32 KB of operator service
output. Controls display the latest 100 permanent before/after audit records;
older records remain in the save. `logs/admin-suite.log` rotates at 1 MB with
three older files. Service logs record fixed routes and response codes, without
passwords, session tokens, request bodies or query strings. Player service logging
remains separate from the operator service log.

The console can run while the game server is online, or when it is stopped.
Reads do not run simulation; pause and suspension settle gameplay to their chosen
boundary before freezing. Starting the shared playtest now happens in this console.
Stop both applications before restoring a backup.

## Correct a saved value

1. Pause the season or suspend the affected account.
2. Reload Administration and open the settlement under **Corrections**.
3. Enter a replacement value and explain the correction, then submit that form.
4. Review the audit's before / after values and resume when ready.

Corrections compare the submitted old value with the current save. A stale,
invalid or rejected submission rolls back the entire transaction.

- Food, Water, Scrap, Metal and Electronics accept finite nonnegative quantities
  within existing storage limits. Reserved offer stock cannot be removed.
- Credits accept whole values up to one billion. Administrative issuance / removal
  has an explicit ledger entry and does not silently alter the Bank reserve.
- Living home citizens' current HP and base morale can be corrected within their
  existing maximum HP and 0–100 morale. These tools do not kill or revive citizens,
  move them, or grant XP / levels. Housing and ration modifiers remain derived.
- Active buildings without unfinished projects accept positive HP up to their
  current level's maximum. This does not rebuild ruins or grant unpaid upgrades.
- Remaining attacks accept whole values from zero through the daily limit.
- Existing active / liquidating loans accept whole debt balances from zero through
  twice original principal. Zero closes the loan; the cap marks it liquidating.
  This is a debt correction, not repayment: it changes neither player Credits nor
  Bank Credits. Borrowed principal cannot exceed the corrected outstanding debt.

Archived settlements cannot be corrected. Unrestricted balance editing, citizen
creation / deletion / revival, and structural schema changes are separate work.

Back up with `./.venv/Scripts/python.exe manage.py backup`. It chooses a unique
backup path automatically; `--output` can select a new destination. See the Flask
guide for the restore procedure. Never restore while a server is running.

## Balance configuration

The console does not yet edit balance settings, starting packages or season duration. See the versioned configuration-editor increment in [the current review](current-game-review-2026-10-11.md). Editing JSON and restarting is a developer workflow, not a safe audited midseason operation.

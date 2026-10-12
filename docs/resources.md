> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# Prototype increment 2: resources and an Administrator

> This guide records its original increment. Later implemented features and current limitations are listed in [the consistency review](review.md).

Run `python app.py` and open http://127.0.0.1:8765 as before. Existing and new
settlements stay paused until Start time is pressed. No schema changes or resets
are required. Before installing this increment, the local prototype save was
backed up to `database/prototype-before-resources.db`.

## Player controls

- Start time / Pause time: advance resources using real elapsed UTC seconds, or
  freeze progression. Paused wall time does not consume supplies or season time.
- Assign Administrator: choose an available living citizen for the Town Hall.
  The previous Administrator becomes unassigned. Assignment history is retained.
- Resource totals refresh every five seconds. Production, consumption, net change,
  and time to empty are shown per hour. Display rounding never rounds saved values.

At the starting values, the Administrator produces 2 Food and 2 Water/hour.
Six citizens consume 6/hour of each. Net use is 4/hour, so 120 units last 30 hours
at unchanged rates. Swapping healthy Level-1 citizens with equal morale keeps
the same rates. More Food/Water buildings are needed in the next increment.

While running, elapsed time is processed on each page/API request and before
an action. Closing the page or stopping the server does not pause the simulation:
the next request catches up from the saved timestamp. Use Pause time first to
freeze the settlement. Requests at the same or earlier processed time do not
consume supplies again. Invalid actions leave the transaction unchanged.

## Prototype boundaries

This is still one local settlement, with the Town Hall as its only producer.
Full rations are used. Construction, new producers, voluntary unassignment,
automatic replacement after death, passive HP regeneration, XP, morale/health
progression, starvation, midnight effects, and multiplayer remain inactive.

As a development safeguard, the entire prototype pauses at the first empty
Food/Water pool, before health consequences. This is not a change to the planned
game's survival rules. Resume is blocked while either pool is empty; refill and
recovery gameplay will come with later increments. Storage clamps prevent negative
or over-capacity balances. At season end, progression stops and the prototype
archives a resource snapshot; full season scoring/settlement is not implemented.

## Configuration and compatibility

`prototype_v1.json` remains unchanged. First Start time upgrades that paused
prototype season to `prototype_v2`, within the same transaction, and records a
configuration event. It preserves citizens, assignments, resources, map, and
Credits. This explicit feature opt-in is a configuration transition, not a schema
migration; SQLite `user_version` remains 1. Unsupported configurations still fail.

The new version retains the starting package and adds workbook values from
Buildings / Citizen Economy / Morale. Production uses the configured level and
morale modifiers and linear current-HP/max-HP condition scaling for the citizen
and Town Hall. This is the minimal interpretation of the GDD's condition scaling;
later healing and morale systems will need their own tests. Rates remain derived,
not saved as additional authoritative fields. Utilities need no resolution yet
because the Town Hall has its built-in utilities.

Pause/resume shifts the season end, finalization, protection, unemployment, and
homelessness timers by paused time; historical creation/assignment timestamps are
retained. Reassignment during a pause uses the frozen game timestamp, so future
unemployment timing resumes from the correct point. Gameplay actions and resource
settlement share a single transaction to prevent partial updates or double-spends.

## Regression coverage

New deterministic tests cover one-hour arithmetic, partitioned elapsed time,
repeat reads, pause/resume, v1 opt-in, storage and depletion boundaries, worker
modifiers, staffing history, invalid/failed assignments, reopened saves,
season-end and suspension freezes, plus browser-facing clock/staffing/API routes.
All earlier tests remain. Tests use supplied clock values and temporary databases;
they do not sleep to simulate game time or modify the player's save.

Next increment: placement and construction of the first Food/Water producer,
with material spending, worker progress, and regression tests for this resource
loop when buildings begin contributing production.

Food construction and Town Hall upgrades are now enabled by the next increment; see [Food guide](food.md). Its v3 configuration supersedes the single-building scope above after the first successful building action.

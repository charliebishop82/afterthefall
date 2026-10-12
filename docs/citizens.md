> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# Citizen consequences

Choose **Enable citizen consequences** to activate `prototype_v13`. It includes
structural combat/recovery and earlier features. Activation is recorded per season
with an effective timestamp for each settlement; offline time before activation is
not subjected to the new rules. Paused time and prototype supply-freeze time do not
age these clocks. Food/Water shortage damage remains separately selectable through
**Enable supply consequences**, as in the preceding prototype.

## Oxygen and evacuation

Unexpected loss of workplace Oxygen coverage or capacity ends the assignment
immediately; residents are reallocated to safe housing by the existing housing logic.
Dangerous assignments outside coverage require an explicit checkbox warning. This
applies to construction, repair crews, scavengers, production workers and guards.

The user approved maximum-HP loss spread over 10 minutes at level 1, plus 0.5 minutes
of tolerance per additional level. Deliberate exposure applies a current -10 morale
modifier; it never accumulates in base morale. Citizens evacuate and become unassigned
at 25% of maximum HP. The protected Town Hall provides a safe evacuation anchor.
Natural healing is disabled during deliberate exposure. Restoring Oxygen ends the
exposure modifier; subsequent unexpected outages cause evacuation.

## Housing and employment

The workbook's existing immediate -10 morale event on becoming homeless remains.
Ongoing homelessness begins removing 1 HP/hour after a 12-hour grace period. Safe
housing resets homelessness. Unemployment lowers base morale by 1/day, prorated after
12 hours; working or being away does not accrue the penalty. These are the currently
implemented routine morale effects; the prototype does not invent an additional
passive return-to-neutral rate. Housing, community and ration bonuses stay current
modifiers. Morale stays within 0-100; the 1/day routine employment loss is below the
workbook's daily negative cap. Explicit combat and expulsion events are separate.

## Midnight UTC population checks

Daily results use a persisted season seed, settlement ID and UTC day, with an audit
entry. Reloading cannot reroll births or departures. Each reached midnight processes:

1. Ordinary desertion: physically home citizens below 35 effective morale have a
   linearly increasing chance up to 10% at zero morale. At least six citizens stay home.
2. One natural birth roll per settlement: workbook base chance 12%, at least one male
   and one female physically home, mean effective morale at least 40, spare safe housing,
   and enough unreserved Food/Water stock plus production for the next 24 hours,
   including the new citizen. Chance starts falling above 75% occupancy and reaches
   zero at full capacity. Away citizens still count toward reserved housing capacity.
3. Minimum population recovery: add level-1 survivors if total living population,
   including deployed citizens, is below six. No replacement is generated merely
   because citizens are traveling.

A birth creates an adult level-1 citizen immediately with a unique name, sex and
persistent identity, level and settlement history. There is no childhood phase.

## Expulsion

The wellbeing panel allows expulsion of an owned, physically home citizen while
retaining six citizens at home. Each survivor loses 3 base morale (user-approved
prototype rule). Departed citizens remain in history, lose assignments, and no longer
consume supplies. Losing the administrator selects the highest-level available
unemployed citizen, breaking ties by XP and settlement seniority.

Captured-citizen integration/desertion is deferred with capture; its distinct workbook
rules are not silently applied to ordinary citizens. Injuries/deaths keep identities
and history. Shortage, homelessness and Oxygen simulations use controlled time in tests.

## Identity and roster corrections

New citizen names are reserved across the whole database so captures preserve
identity without introducing new name collisions. Existing names are unchanged;
legacy duplicates in a settlement roster display their citizen IDs. Births and
population-floor arrivals receive generated full names. New floor arrivals have
random male/female demographics using the persisted simulation seed; no guarantee
of both sexes is added. The current roster displays sex and XP through V13.

> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# Supplies, rations and shortage recovery

Choose **Enable supply consequences** in the Supplies and rations panel. This
explicitly replaces the prototype shortage freeze for your settlement. Existing
saves are not changed merely by installing this increment. Previously frozen time
is not retroactively punished; an administrative suspension cannot be lifted by
this control. The original sandbox still supports manual pause/resume.

Food and Water each support Full, Reduced and Emergency rations. Consumption comes
from the current workbook's Citizen Economy rows: Food 1 / 0.75 / 0.5 and Water
1 / 0.8 / 0.6 units per citizen per hour. Their current morale modifiers are Food
0 / -3 / -8 and Water 0 / -5 / -12. The user chose current modifiers to resolve the
conflict with the Morale sheet's daily interpretation. Returning to Full rations
removes the modifier; saved base morale is not repeatedly reduced. Housing modifiers
continue to apply separately. Citizens deployed on raids do not consume home supplies
or receive home ration modifiers and shortage damage.

An actual shortage begins when accessible, unreserved stock is empty and production
cannot meet current consumption. Empty storage alone is not a shortage if current
production covers demand. Reserved trade stock and inaccessible Cold Storage Food
do not satisfy needs. Production, construction, military manufacturing and scavenging
continue, allowing the player to recover through staffing, new collectors, scavenging,
trade or reduced consumption.

The user approved these configurable prototype values because the sources leave
exact shortage damage unspecified:

- Food: six hours of continuous shortage grace, then at most 2 HP/hour.
- Water: two hours of continuous shortage grace, then at most 4 HP/hour.

The two losses add. Partial production reduces each loss by the fraction of demand
it supplies. Health, productivity, population and rations therefore change the
following interval's shortage damage. Once stock is accessible or production meets
demand, that shortage ends and its grace timer resets. Returning shortages receive
a fresh grace period. Natural healing resumes when both needs are met and safe
housing is available, using the existing 2 HP/hour rule.

Damage is accrued on the existing simulated-minute grid, with grace, depletion,
production and job boundaries settled first. Reopening after offline time and frequent
refreshes produce the same saved result. Zero HP records permanent death and closes
assignment and settlement history; survivors receive the existing capped death morale
effect. A vacant Administrator is replaced by the highest-ranked idle home citizen
when available. Existing midnight population recovery replenishes living population
below six; the settlement itself remains active even if citizens die.

Emergency rations currently use their listed consumption and morale values. Extra
health damage from prolonged Emergency rations with otherwise sufficient supplies
is deferred because its timing/rate remains unspecified. This increment does not
add homelessness damage, Oxygen exposure, daily morale drift, births or desertion.
No balance source or older versioned configuration is edited.

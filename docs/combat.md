> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# Citizen and drone resource raids

Update 2026-10-08: configuration v10 adds [guard/patrol controls](support.md) and
[offensive and defensive drone combat](drones.md). The citizen-only rules below
describe the earlier baseline; their drone/Guard Post deferrals are superseded.

Account mode (`python accounts_app.py`, http://127.0.0.1:8767) now includes Citizen
raids. Declare war with another active settlement, wait the workbook's one-hour
warning, then select your own idle citizens and a resource objective. Resolution
occurs after a fixed one-hour operation. No voluntary recall is available.

All values come from the current V1 Building Settings workbook, copied into
`config/combat_v1.json`, and GDD v0.2 sections 20–24. Existing balance configurations
and source documents are unchanged. The following prototype choices are explicit:

- The user approved injuries equal to the listed casualty coefficient times each
  participant's maximum HP: clean winner 10%, clean loser 30%, contested 20%.
  Damage bottoms out at zero; zero HP records death and preserves identity/history.
- Equal arrival timestamps resolve in ascending attack ID. This fills the GDD's
  otherwise unspecified deterministic tie-break rule.
- A contested fight returns no loot. Clean attacker victory requires the workbook's
  10% margin; loot additionally requires surviving strength of at least one.
- Resource-only raids have no targeted building. Available idle citizens and
  existing explicit defender/patrol assignments participate; ordinary workers
  elsewhere continue their jobs. Guard Posts and their construction UI are deferred.
- Balanced loot is proportional to accessible physical resource pools. A preferred
  resource is taken first; any remaining carrying capacity falls back to Food,
  Water, Scrap, Metal and Electronics. Balanced overflow deposits use that same order.

New settlements retain 24-hour beginner protection. Protected players may declare
war, but cannot be attacked until their shield expires. Launching an attack ends
the attacker's own protection. Launch validates the season, warning, protection,
treaty blocks/cooldowns, selected citizen ownership, integration, health and daily
allowance. Offensive citizens need at least 25% maximum HP and must be unassigned.
At least six living citizens must remain physically home, regardless of their
health or normal work. Rescue additional citizens by scavenging to exceed the
starting six; this increment does not grant free raiders or bypass protection.

Three attack allowances reset at midnight UTC. A request settles elapsed time to
each reached midnight before applying its reset. If the living population is below
six, level-one survivors arrive with normal starting HP and morale. Deployed living
citizens count toward population, preventing deployment from generating replacements.
Midnight processing precedes a battle arriving at exactly midnight. Prototype supply
freezes still stop personal simulation; this is separate from public server scheduling.

Committed citizens are marked away in saved state, cannot be reused for construction,
repairs, scavenging, administration or another attack, do not consume home Food/Water,
and do not earn work XP or natural healing while deployed. Their housing places remain
allocated as residents, but their housing morale modifier does not apply while away.
Survivors return immediately upon resolution; casualties and loot commit together.

Strength uses workbook base 10 plus one per level above one, current HP with the
35% alive contribution floor, and current morale bands (75% below 35, 100% below 75,
110% otherwise). Each side receives an independent deterministic ±10% variance roll
from the saved server seed. Surviving combat participants earn 10 XP, plus 10 for a
clean victory, with normal level thresholds. Morale applies the workbook's returning
raider, defending settlement and capped death effects. Injured survivors can heal
after returning; deaths close assignment and settlement history rather than deleting
the citizen.

Carrying capacity is 12 physical units per surviving raider plus 0.5 per level above
one. Only accessible, unreserved resources can be stolen. Reserved trade contributions
and inaccessible Cold Storage Food remain safe. Loot is removed from the defender,
then deposited up to the attacker's current storage capacity; excess is lost and
shown in the report. Credits/Vault raids, capture, drones, missiles, structural
damage, patrol controls and general treaty management remain later increments.

Defenders see only an anonymous hostile countdown before arrival. War declarations
notify both settlements immediately, but incoming attacks do not disclose identity,
composition or objective. After resolution, only the two participants can read their
private battle reports. Reports show names, outcome, strengths, injuries, and stolen,
delivered and lost loot. Internal audit records and seeds are not served wholesale.
Countdowns refresh with the existing five-second polling interface.

Any account gameplay action settles all due attacks in the shared season before
advancing beyond their arrival times. Both participating settlements are settled to
arrival inside the same write transaction, then later time uses the injured/returned
state. Multiple battles resolve sequentially using previous results. Invalidated
protection, war/treaties, frozen or unavailable participants cause a system recall,
release assets and refund an allowance once, capped at the current daily maximum.
Season end recalls remaining pending attacks. New declarations/launches close during
the final three-hour window; already launched raids may still finish.

Run `python run_tests.py`. Combat tests use disposable databases, controlled clocks
and saved deterministic rolls. The original single-player save remains separate and
does not show conflict controls. Localhost hosting, account prototype supply freezes,
and the earlier deferred full season-scoring/archive limitations remain unchanged.

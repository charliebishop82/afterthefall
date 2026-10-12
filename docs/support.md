> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

Current maintenance and voluntary building removal are documented in [Maintenance guide](maintenance.md). Earlier deferred notes below describe the previous increment.

# Support buildings and citizen defense

Choose **Enable support and defense**. This extends the shared season to configuration
v10, preserves existing saves/clocks and does not enable supply consequences.
New joins retain the season's catalog. Sources and previous configurations are unchanged.

All workbook levels, costs, HP, footprints, unlocks, utilities and staffing limits
are included for Clinic, Medical Center, Salvage Depot, Trading Post, Community Center
and Guard Post. Engineering Workshop already existed; its support bonus now works.
Use the ordinary construction, upgrade, worker and repair controls.

The user approved the following prototype interpretations on 2026-10-08:

- Effective support factor = building condition times summed worker productivity,
  divided by that level's maximum workers, capped at one. Minimum staffing, safe
  Oxygen and mandatory Electricity must be satisfied first. Upgrade/construction
  and shutdown conditions suspend benefits. Duplicate buildings do not stack;
  each effect uses the strongest active value.
- Engineering Workshop improves construction/upgrade and **crew** repair speed.
  It does not accelerate passive Town Hall regeneration or manufacturing.
- Salvage Depot improves scavenging speed and ordinary **material** recovery.
  Material yield applies to each interval's Scrap/Metal/Electronics delivery;
  staffing changes affect future delivery only. Food/Water yields and survivor
  probabilities remain unchanged. Normal storage overflow still applies.
- Community Center adds a current home-citizen morale modifier. Power coverage
  multiplies it by the workbook's 125%; the base benefit works without power.
  Removing staffing/power removes the relevant benefit, without daily accumulation.
- Clinic/Medical Center accelerates the existing 2 HP/hour natural healing rate.
  The strongest functioning medical facility with at least one usable treatment slot is used, without combining duplicate
  capacities. Treatment capacity scales with staffing/condition and rounds down.
  Eligible patients are ranked by HP/max HP, then citizen ID, and each receives
  treatment once. Food, Water, safe housing, home presence and living HP remain
  necessary. Clinic needs no electricity; Medical Center does. Treatment is automatic;
  patients keep their existing assignments. Credits use the existing recovery clock,
  preserving offline and frequent-read equivalence.
- Trading Post is constructible and upgradeable, with workbook market-fee reduction
  displayed. In account mode the strongest functioning staffed Trading Post reduces
  public market fees. Private trading is free and does not require a Trading Post.

Guard Posts use **Assign guard** instead of production workers. The support panel
assigns/releases **Patrol**, and releases guards. Citizens must be living, owned,
home and unassigned; guard/patrol/work/administration are mutually exclusive.
Guard capacity follows each workbook level. Assignments persist through outages;
unsafe, damaged or upgrading posts stop contributing until operational again.

For current resource-only raids, the user approved the Town Hall as the local
coverage point: its center must be within the Guard Post's rounded footprint radius.
Each eligible guard contributes ordinary citizen combat strength. A working post
adds its listed Defense Strength times effective support factor, plus the workbook's
8 strength per guard times post condition. Different covering posts contribute;
a citizen participates once. Patrol has settlement-wide response and the workbook's
15% citizen combat bonus. Ordinary workers elsewhere do not defend.

Guard radii appear on the map. Readiness counts show only operational local guards
and available drones. Guards/patrols continue home consumption and healing; they
are not raiders and do not bypass the six-home-citizen rule. No passive defense XP
is granted; surviving battle participation uses existing combat XP.

Later increments enable turrets, structural damage, ruin salvage and citizen
consequences; see structural.md and citizens.md. Account-mode public markets
and diplomacy are described in social.md.

Utility allocation keeps the existing provider-startup rules. For v10 consumers,
Oxygen eligibility follows Housing > Medical > Water/Food > Industry > Support;
Electricity then follows Water > Food > Medical > Defense > Industry > Support.
Oldest completed buildings break ties. Capacity released by an Oxygen-eligible
consumer that cannot obtain Electricity is retried for remaining consumers, rather
than held by an idle building. Defensive bays/batteries use the Defense electricity
tier. Earlier configurations retain their established allocation behavior.

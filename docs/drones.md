> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

Current maintenance and voluntary building removal are documented in [Maintenance guide](maintenance.md). Earlier deferred notes below describe the previous increment.

# Drone resource raids

Enable **support and defense** to unlock finite drone deployment in account mode.
Manufacture offensive drones in a staffed Drone Factory and house them in an
operational Offensive Drone Hangar. Select individual drones in the existing raid
form, alone or with eligible citizens. Resource objectives, one-hour war warning,
protection, treaties, one-hour travel time, three daily attack allowances and the
final-three-hour launch cutoff remain unchanged. Six living citizens must remain
home; pure drone raids therefore work with the initial six citizens.

Only owned, available, living offensive drones with operational home hangars can
launch. Deployment reserves their individual unit rows and home storage slots.
They cannot launch twice. A system recall returns surviving drones and refunds
one attack allowance idempotently. Season-end recalls also return deployed assets.
The defender sees only the existing anonymous incoming countdown until resolution.

The user approved these prototype combat interpretations on 2026-10-08 because
GDD v0.2 explicitly leaves exact drone phase order/formulas open:

1. Available operational Air Defense Drones automatically fight offensive drones.
   Both sides use workbook strength, persistent HP scaling with a 20% floor while
   alive, saved deterministic variance and the existing clean-win/contested margins.
2. Living offensive survivors join the resource raid alongside selected citizens.
   Operational Ground Defense Drones automatically join the defense **only when
   the attack includes living citizen raiders**. Home idle citizens, patrols and
   eligible local guards defend as before. Air Defense Drones do not fight citizens.
3. Each engaged phase applies 10% maximum-HP injury to a clean winner, 30% to a
   clean loser, or 20% to both in a contested result. An offensive drone fighting
   in both phases can receive two injuries. If aerial defense destroys every
   attacking asset, no ground/resource fight occurs and no resources are stolen.
4. Zero HP permanently destroys the drone and frees its storage slot. Survivors
   retain HP and return to their assigned home; there is no automatic drone healing.
   Drones have no names, XP or citizen identity.
5. A clean resource victory uses surviving carrying capacity: 20 physical units
   per returning offensive drone plus existing citizen capacity. Trade reservations,
   inaccessible Food, storage overflow and resource priority still apply. Air-phase
   victory alone does not grant loot. Contested resource fights return no loot.

Workbook strengths are Offensive 30, Air Defense 28 and Ground Defense 25 at full HP.
Defensive units are selected at arrival, so staffing, utilities, bay availability
and earlier battles affect each sequential resolution. Battle reports are private
to the two participants and show air/raid phases, drone HP/losses and loot.

Missiles/interceptors can still be manufactured but cannot be launched or expended.
Drone servicing and Repair Drone actions are now available with maintenance enabled. Turret combat, capture, allied defense and structural damage remain deferred.

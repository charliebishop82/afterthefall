# Versioned configuration

`prototype_v1.json` contains the small subset of the current V1 workbook needed
for the first saved-settlement prototype. Source sheet/setting notes are included
in the file, and automated tests compare starting resources and Town Hall values
with the original workbook. The full catalog is not imported yet.

Do not edit a configuration version in place once saved seasons refer to it.
Add a new version and explicit compatibility or migration handling. The GDD is
the gameplay authority; the workbook supplies content and numerical balance.
Resolve the discrepancies in `docs/database_decisions.md` before implementing
affected systems. Source documents remain read-only.

Prototype increment 2 adds `prototype_v2.json` for resource rates and staffing.
Existing saves retain v1 until Start time explicitly enables v2. The change is
audit-logged and preserves saved state; see `docs/resources.md`. Neither version
should be edited in place once used by a save.

`prototype_v3.json` adds workbook-backed Food buildings and Town Hall levels. It is enabled by the first successful building command, without resetting a save or changing SQLite schema. Construction formula interpretations are documented in `docs/food.md`. Older configuration files remain unchanged.

`prototype_v4.json` establishes the civilian economy and scavenging. The user-approved Warehouse unlock is Town Hall 1; other catalog values follow the workbook. Enabling production records the configuration transition and adds derelicts without resetting existing state. See `docs/production.md`.

`prototype_v5.json` adds housing and survivors without changing older settings.
Housing types are independently buildable as requested by the user, with fixed
workbook footprints and workbook upgrade levels. Enabling v5 retains all loot and
work progress and initializes one private survivor opportunity per uncleared ruin.
See `docs/housing.md` for rules and deferred effects.

`prototype_v6.json` adds natural recovery and current housing morale modifiers.
The workbook supplies 2 HP/hour and +1 powered comfort; housing bonuses retain
their existing workbook values. Healing uses a fixed simulated-minute grid with
persistent qualifying seconds to make offline and frequent-read progress agree.
Enabling v6 preserves base morale and all earlier state. See `docs/recovery.md`.

prototype_v7.json adds Citizen Economy work XP rates and cumulative level thresholds, preserving all v6 building and recovery values. Activation is explicit.


prototype_v8.json adds user-authorized prototype repair settings: 20 HP/hour per equivalent repair worker, 50% cumulative materials scaled to missing-health fraction, and 1 HP/hour staffed Town Hall regeneration. All workbook catalog and earlier feature values are preserved.


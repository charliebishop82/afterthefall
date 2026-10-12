> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# V1 database implementation decisions

> This guide records its original increment. Later implemented features and current limitations are listed in [the consistency review](review.md).

## Scope and source mapping

`database/create_database.py` implements all 40 tables in database-design v0.1,
section 19. GDD v0.2 controls gameplay; the Building Settings workbook controls
content identifiers and numerical balance. No starting package, catalog, player,
season, or administrator credentials are seeded. `game.db` is intentionally empty.

The script is the executable initial schema, not a migration framework. SQLite
`user_version = 1` records the schema revision separately from season config
versions. STRICT tables reject incompatible storage types, including fractional
Credits. Fractional Food, Water, materials, HP, work, and XP are supported.

## Representation choices

- Times are UTC Unix seconds in INTEGER columns. Required times are explicitly
  supplied by the server, never silently filled from a client's clock. No game
  ticks or per-second rows are created. The server must validate timestamp order
  where it is not already checked by the schema.
- Numeric primary keys are internal identities. Names use SQLite's default exact,
  case-sensitive uniqueness. Any future case-insensitive login policy must be an
  explicit decision. Renaming fixed public/citizen names is not a game feature.
- Foreign keys default to NO ACTION; there is no cascade deletion. Lifecycle
  status and timestamp changes preserve records. The future server must prohibit
  history deletion and enforce read-only season archives and admin authorization.
- The optional `citizens.current_assignment_id` cache is omitted. Query the
  authoritative open assignment instead. A partial unique index permits at most
  one open assignment and one open settlement membership per citizen.
- Job `target_id` is refined into three nullable foreign keys plus `target_type`.
  Exactly one building, private derelict, or unit must be selected. This avoids
  an unenforceable generic gameplay target. Building ruins stay in `buildings`;
  their salvage/clear jobs target that building. Base-map derelicts use the two
  derelict tables. Job work is authoritative; do not duplicate progress on ruins.
- Manufacturing has a producing building, output configuration ID, batch quantity,
  queue position, and repeat flag. Only one active or paused manufacturing job
  occupies a producer; queued jobs do not. `inputs_spent` records actual paid
  materials for refund/salvage audit without introducing material reservations
  for construction.
- Settlement fields track remaining attacks, last rollover, suspension timing,
  and rebuilding eligibility. They support GDD state that cannot be derived only
  from current buildings. Their zero/boolean defaults are structural defaults,
  not a starting package. Joining a season must explicitly apply configuration.
- Seasons include map seed, pause timing, last rollover, and an optional frozen
  final snapshot. Frozen score/statistic snapshots are allowed; live derived
  scores, capacities, utility balances, productivity, and max HP are absent.
- Same-season composite foreign keys protect attacks, diplomacy, market/trade
  parties, loans/investments, and private base-map derelicts. Composite building
  foreign keys keep stored hardware, Vault allocations, and building jobs local.
- Combat participation records retain original settlement, role, and outcome.
  Allied hardware uses `ally` roles. Open participation rows prevent simultaneous
  commitment to two attacks. Completion/cancellation releases them transactionally.
- Treaty pairs are canonical (`settlement_a_id < settlement_b_id`). Different
  treaty types may coexist; duplicate proposed/active treaties of the same type
  may not. Expiry/cooldown history remains after cancellation. War can become
  active without acceptance; `effective_at` supports the warning period.
- Credits and financial amounts are whole integers. Bank Credits may be negative;
  settlement Credits and outstanding balances may not. Daily rates are decimal
  fractions (e.g. 0.02), not percentages. The server will apply configured rounding.
  Private trade/reservation Credits must also be whole numbers. Market quantities
  are whole resource units, as specified in Economy Diplomacy. Unit prices are
  whole Credits; support for fractional unit prices would need a precision decision.
- A ledger row records one signed movement. Null `settlement_id` denotes the Bank;
  a shared `transfer_ref` groups legs of a transfer. Future services must balance
  transfer legs and enforce the no-borrowed-Credits-for-investment rule.
- JSON text is checked with `json_valid`. It is used for audit/report details,
  immutable transaction terms, spent materials, random results, and final snapshots,
  not in place of the principal relational state. Server code must validate each
  payload's shape and quantities. Generic audit/notification target references
  intentionally are not foreign keys; `death_related_id` is interpreted by cause.
- Derelict key references/nonces and private results support reproducible private
  loot. Secret keys belong in server-controlled storage, never in the browser.
  Attack seeds and internal audit data must also remain administrator-only. Store
  redacted recipient-specific results in `battle_reports` and `news_events`.

## Game-service checks still required

Schema integrity does not implement gameplay. The next server increment must
validate configuration IDs, ownership on citizen/derelict/unit job operations,
citizen origins/captures within the same season, assignment targets, full rotated
footprint boundaries and overlap, Town Hall rules, max HP/levels, workforce,
resources available after reservations, reservation/listing/trade consistency,
asset ownership/availability at launch, and legal actions by season/settlement
status. It must update authoritative balances and history together.

Simulation, rollover, suspension/resume, archive freeze, protected raids, material
consumption, debt provenance, citizen-name generation, and atomic trade/combat
resolution remain game logic. Required ordering: midnight first, then attacks by
`resolves_at, attack_id`. Add tests alongside each service, not invented mechanics
to the schema creator.

## Source discrepancies to resolve before affected game logic

These do not block an empty schema and were not silently resolved here:

1. GDD section 14 describes geometric utility zones without quantity/capacity
   networks. Workbook Utilities/README adds capacity plus coverage and shortage
   priorities. Both prohibit accumulated utility balances; the schema stores none.
2. GDD section 13 loses storage overflow immediately. Workbook Utilities audit
   correction says unpowered cold storage makes excess Food inaccessible rather
   than destroying it. There is one Food pool; future availability logic needs an
   agreed interpretation.
3. GDD section 17 fixes Town Hall utility radii through upgrades; Buildings lists
   radii 4/5/6. No radius is hard-coded or copied to building instances.
4. GDD section 7 prevents duplicate citizen names within a settlement and preserves
   names after capture. Two settlements may generate the same name, so capture
   can create a collision. The schema intentionally avoids a uniqueness constraint
   that would block capture or require a forbidden rename. Generation must avoid
   local collisions; capture collision policy remains to be agreed.

## Validation

The standard-library unittest suite checks fresh schema creation, all inventory
tables, foreign keys, range/type constraints, season scoping, history retention,
active assignment/deployment/manufacturing uniqueness, treaty coexistence, valid
fractional resources and negative Bank balances, failed-transaction rollback,
safe repeat invocation, and failed-initialization cleanup. It uses temporary files.

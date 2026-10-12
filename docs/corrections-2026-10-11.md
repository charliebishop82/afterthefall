> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# Corrections from the content review

This change addresses the seven confirmed inconsistencies in
[the 11 October review](content-review-2026-10-11.md). Source documents,
balance values and deferred seasons remain unchanged. No new packages or schema
migrations are required.

- Hostile damage stops the Town Hall at 25% of its current level's maximum HP.
  Repeated damage at that floor causes no additional occupant injury or repair
  work. Admin corrections enforce the same minimum. Older saves already below
  the floor are not healed by an attack; use an audited correction while frozen.
- Captive desertion/integration runs before Bank interest and liquidation, using
  fresh state between phases. Midnight processing still precedes same-time combat.
- New identities are unique across the database. Captures retain names and IDs.
  The user's chosen compatibility policy preserves existing names and distinguishes
  legacy duplicates with citizen IDs in the roster.
- New births and population-floor survivors receive generated full names. Floor
  arrivals receive seeded male/female demographics, permitting normal birth
  eligibility when supplies, housing and the demographic requirements are met.
  Existing identities and demographics are not rewritten.
- The current roster shows XP and sex, including V13.
- Board moderation is available only in the independent admin console. Player
  communication rejects hide/restore even for admin accounts. Hidden posts remain
  available to the console and moderation remains audited.
- Continuous output and XP reflect useful throughput. Full Food/Water pools permit
  replacement consumption; near-full pools permit proportional work. Converters
  preserve inputs and usable output, including at full shared storage and with
  competing workers. Reserved resources remain protected. Salvage that cannot fit
  is discarded before it can waste converter inputs; clearing work still counts.

## Verification

Twenty-one new regression scenarios accompany the corrected original expectations.
The original Town Hall and admin correction tests now enforce the locked 25% rule;
the moderation test uses the independent console service and adds player rejection.
The full suite passed: **578 tests**, including 21 new checks and 2,000 seeded
converter combinations (2235.579 seconds). No tests were skipped.
Installation uses verified file fingerprints and retains a backup of replaced code. All verification uses temporary
databases, controlled clocks and seeded randomness rather than player saves.

## Remaining work

The review's source conflicts still need explicit decisions. Advisor/notification
coverage, performance, end-to-end playtesting and public hosting are follow-ups.
Full season completion and rollover remain deferred as requested.

> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# Market, diplomacy and player communication

These features run in account mode (`python accounts_app.py`, port 8767).
The single-settlement prototype on port 8765 has no other player accounts.
No new dependencies, schema migration or economy-profile switch is required.
Use the Market, Diplomacy, Messages and Board links near the account bar.

## Public market

Player listings have been replaced by season-wide pooled stock. Sell unreserved
whole units immediately to the Bank; other players can buy those goods from the
pool. Stock starts empty and is never automatically replenished. Buying prices
are 2/2/3/6/15 Credits for Food/Water/Scrap/Metal/Electronics; gross selling prices
are 1/1/2/4/10. The seller pays the 8% fee, reduced by their strongest functioning
Trading Post with a 2% minimum and upward whole-Credit rounding. Trade agreements
no longer affect market transactions. Zero-net sales are rejected; batch small sales.
Spendable goods/Credits, receiving storage and normal season/suspension
restrictions are checked atomically. All transfers are logged. Shared stock is
unlimited in capacity but finite in quantity and scoped to its season.

Daily personal reserve limits remain 30 Food, 30 Water, 20 Scrap, 10 Metal and
5 Electronics at 2/2/3/6/15 Credits per unit. They reset at UTC midnight with no
carryover; shared-market purchases do not use them and reserve purchases do not
deplete pooled stock. A player may resell purchased goods at the lower selling
price, never for a guaranteed profit. Direct trades remain independent and fee-free.

Restart automatically cancels legacy open listings, releases their reservations
and preserves history. Goods stay with their owner; they are not added to the pool.
Prices are editable in config/market_pool.json; reserve limits remain in
config/market_reserve.json. Seller prices must be below both buying prices.

## Diplomacy

Peace, Non-aggression and Trade Agreement are independent bilateral treaties;
multiple types can coexist. Proposals require acceptance by the other player and
expire after 48 hours. The proposer can withdraw a pending proposal; the recipient
can reject it. Either participant can cancel an active treaty. The same treaty
cannot be re-proposed for twelve hours after cancellation.

Accepted Peace/Non-aggression blocks raids and immediately system-recalls inbound
attacks between the pair, returning participants/ammunition and refunding attack
allowances once. Peace also closes an active War declaration. Cancelling Peace
leaves a six-hour hostility cooldown; cancelling Non-aggression leaves twelve
hours. Existing unilateral War declaration and its one-hour warning remain.
Trade Agreements remain available but no longer affect pooled-market prices or fees; they do not prevent hostile action.
Treaty changes produce participant notifications and public acceptance/cancellation
news. No arbitrary treaty relationship cap is introduced.

Mutual/Full Defense and allied hardware contributions are deferred to a separate
combat increment; the interface does not offer treaties with incomplete effects.

## Messages and board

Private mail has an inbox, outbox, read status, archived inbox and archived outbox.
Only sender/recipient can view a message; only the recipient marks it read.
Archiving one side does not remove the other side's copy. All messages persist.
Subjects allow 80 characters, bodies 1,000. The season board shows the latest fifty
visible posts, also up to 1,000 characters. Administrators can hide/restore posts
with a reason; before/after moderation status is permanently audit-logged.
Hidden posts are excluded from ordinary players' pages.

Prototype request limits: twenty private messages or ten board posts per real
minute per account. Text is escaped when rendered. New messages, board activity,
market changes and treaty updates wake the existing page refresher. Communication
works while gameplay is paused or supply-frozen; finished seasons reject new
messages/posts and retain history. Read/archive flags can still be updated.

Public news currently includes war declarations, treaty acceptance/cancellation
and resolved raids. Public raid headlines identify the two settlements only;
exact damage, loot and combat audit inputs remain in the existing private reports.
Participant market notifications include price and seller fee. Notification read
status is stored per account. Broader milestone/Bank-health news, Bank loans,
investments, push notifications and real-time chat remain outside this increment.

## Independent moderation

Post hiding and restoration are available only through the independent admin
console. The player communication service rejects both actions, including for
admin accounts. Player pages show visible posts only; the console retains hidden
posts and the permanent moderation audit.

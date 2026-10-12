> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

# Direct player trading

Run `python accounts_app.py` and open http://127.0.0.1:8767. The Player trading
panel appears after creating an account settlement. Two players must create
settlements in the same season. Use separate browser profiles, or log out and
switch accounts: tabs in one profile share the login cookie.

Choose the other settlement, the resource and quantity to give, and the resource
and quantity to receive. Submit a proposal. Its recipient can accept or reject;
its proposer can cancel. The browser form keeps this first increment small with
one resource on each side; the transaction service also supports several resources.
Food, Water, Scrap, Metal, Electronics and Credits can be exchanged. Both sides
must contribute a positive amount. Physical quantities may be fractional; Credits
must be whole numbers. Malformed, non-finite and excessively large quantities are
rejected. The panel lists the latest 30 participant proposals and updates through
the existing five-second page refresher.

The current V1 Building Settings workbook, Economy / Diplomacy sheet, specifies
zero direct-trade fees, a 24-hour expiry and ten outgoing pending proposals per
settlement. GDD v0.2 section 20 requires an atomic exchange. The V1 database design
requires immediate reservations, storage accounting and capacity revalidation.
No balance values or source documents changed.

Only the proposer's contribution is reserved while a proposal is pending; the
requested contribution is checked at acceptance. Reserved resources remain in
their physical storage and are unavailable for construction, upgrades, repairs,
conversion, consumption or another offer. A reservation is released exactly once
on acceptance, rejection, cancellation or expiry. Inaccessible unpowered Cold
Storage Food cannot be offered. Damage or lost storage capacity cannot discard
committed resources.

Acceptance settles both participants' elapsed time, rechecks accounts, season,
ownership, reservations, available resources and both final storage totals, then
exchanges everything in one `BEGIN IMMEDIATE` SQLite transaction. Insufficient
stock or space leaves the proposal pending and transfers nothing. Existing legacy
overflow may be retained but a trade cannot increase it. Credits use paired audit
ledger entries with a shared trade reference; the Bank does not fund private trades.
Repeated or concurrent acceptance cannot duplicate the exchange.

Only participant proposals are visible. Other players' settlement names are public
for choosing a recipient; their resources, citizens and map state remain private.
Authentication, per-session CSRF, origin and form-size checks apply to trade actions.

Expiry is settled on requests, including a recipient read when the proposer is
offline. Active simulation splits at the exact expiry boundary so resources are
not retroactively consumed before their reservation ends. Frozen settlements stay
frozen until their next request/exchange supplies accessible Food and Water; recovery
does not simulate starvation during the prototype's supply freeze. Personal recovery
and citizen/protection timers shift by the frozen duration; shared season deadlines
continue unchanged. Trading can recover this specific prototype shortage freeze;
it cannot lift an administrative suspension or archived state.

New proposals and acceptances close during the final three-hour settlement window.
Cancellation and rejection remain available before season end. Season-end handling
expires remaining proposals and releases their reservations. Full multiplayer
season scoring/archive orchestration remains deferred, as in the account increment.

This increment activates private trading in account mode only. Public markets, basic treaties and messaging are now available; see social.md.
Loans remain a separate increment. Basic citizen raids are
now available in account mode; see docs/combat.md. The original local
single-player save has no other players and does not show trading controls.

Run `python run_tests.py` for the complete regression suite. `tests/test_trading.py`
uses disposable databases, controlled clocks and seeded maps; it checks source
values, completed exchanges, reservations, rejection/cancellation/expiry, ownership,
capacity, construction/repair/production interactions, supply recovery, concurrent
acceptance and authenticated HTTP forms.

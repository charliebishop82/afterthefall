> **Current status:** See [the complete game review](current-game-review-2026-10-11.md) for implemented behavior, approved rules and remaining work. This guide retains its original increment/compatibility details; current shared playtests start enabled in v13.

> **11 October economy update:** expansion-enabled games now include renewable
> Scrap from staffed Salvage Depots. See [the building/economy review](building-economy-review-2026-10-11.md).

# Expansion prototype

This opt-in account-mode increment adds allied defense, citizen capture, Credit
raids and Vaults, public scoring, and Bank loans/investments. Enable it from the
Bank section. Activation applies to the shared season and starts the new rules
at activation time; it does not replay financial or capture consequences before
activation. Existing configuration files and reference documents are unchanged.

## Authorities

The latest source Building Settings workbook supplies score weights, valuations,
Vault construction and capacities, capture defaults, Bank rates, and terms.
`config/expansion_v1.json` records those settings and approved prototype choices.
The GDD remains the gameplay authority where the workbook does not specify a
rule. Defense treaties use the workbook's explicit non-blocking treaty rule;
Peace and Non-aggression remain the treaties that prevent attacks.

## Allied defense

Only direct, active Mutual/Full Defense partners participate. Duplicate treaties
do not multiply support and support never chains. Each ally offers 25% of its
available hardware, rounded down separately for each defensive drone type and
interceptors. Local hardware fights first. Drones are drawn evenly, with the
starting partner rotated by attack ID, until the additional strength is no
longer needed. Interceptors are drawn evenly only after local stock is spent.
Turrets remain local. Units and ammunition are debited from their actual owners.
Allies receive private contribution notifications and an audited contribution
report; they do not receive either settlement's private full battle report.

## Citizen capture and Credits

Population raids need citizen raiders. Successful focused raids roll 25% per
eligible surviving home defender, capped at three captures. Other successful
raids use the workbook's 2% incidental chance for participating defenders.
Failed surviving raiders use the workbook's 8% capture chance. Capture preserves
identity, experience, level and health and records ownership history. Captives
start at 20 morale, may work immediately, and may not raid until integrated.
At the next active UTC midnight they face a desertion risk rising linearly to
50% below 35 effective morale; survivors integrate. They do not also receive an
ordinary desertion roll that midnight. Captive desertion can reduce population
below six; the existing midnight floor then restores six. Pauses defer the
integration check until the next active midnight after resumption.

Credit raids take at most 20% of unprotected, unreserved Credits, without using
physical loot capacity. Vaults unlock at Town Hall 2 and upgrade through level
3. A powered Vault protects its full 500/1000/2000 capacity at any positive HP.
An outage removes protection while retaining allocated Credits. Destruction
permanently burns 25% of allocated Credits, exposes 50% to that same successful
mixed/citizen/drone attack, and retains the other 25%. Missiles alone do not
collect Credits. Original allocations are snapshotted for each attack so chain
hits cannot repeatedly expose the same balance. Reserved trade Credits stay
outside raid and Vault allocations.

## Scores

Population, Military, Wealth and Development each contribute 25% of normalized
Overall, relative to their category leader. Negative Wealth stays negative;
when no positive Wealth leader exists, normalization uses the largest absolute
negative value. Ties compare Development, Population, Wealth then Military;
exact ties share competition rank. Public output contains category totals,
Overall, rank and settlement name only. Owned deployed hardware counts once;
spent ammunition, destroyed drones and ruined buildings do not count. Private
inventories and maps remain private. Account reads advance participating
settlements to the same simulation time before producing public rankings.

## Bank

Each joined settlement contributes 2000 reserve Credits once. Loans have a
minimum of 50 Credits; total remaining principal is capped at 35% of current
settlement value. Borrowed cash and principal cancel in collateral value,
preventing recursive borrowing. New loan rates start at 2% daily and reflect
Bank reserve pressure at opening. Rates are fixed for that contract. Interest
capitalizes at UTC midnight, prorated for the first interval, rounded upward to
whole Credits per daily interval. Debt never exceeds twice original principal.
Partial repayments pay interest before principal. Debt creates a reversible
current morale modifier up to -15, beginning at the workbook's 20% debt ratio.

Investments offer 3/7/14 days at base daily returns 0.75/1/1.25%, adjusted for Bank
health at opening. Borrowed-fund checks subtract remaining borrowed principal
from unreserved Credits. Investment interest is simple; fractional Credits
carry forward until a whole Credit is earned. Maturity pays automatically and
only once. Early withdrawal returns principal and forfeits accrued interest.
Bank failure is disabled; payouts can make the reserve negative.

At the debt cap, liquidation first uses cash, cancels outgoing reserved offers,
then sells stored hardware, investments, resources and buildings at workbook
resource valuations. Deployed hardware cannot be sold. Town Hall is protected,
and liquidation does not remove citizens. Each sale and financial transfer is
audited. Insufficient assets leave the capped loan liquidating for later
repayment. Pauses shift financial clocks. Existing season closure returns
investment principal and accrued whole interest, repays debt from available
cash, and retains unpaid debt in final Wealth without further interest.
Complete season awards, rollover and new-season creation remain deferred.

All financial transfers have paired player/Bank ledger entries. Vault burns
are explicitly unpaired destruction entries; Credit raids have paired player
entries. No schema migration or new runtime dependency is required.

## Corrected midnight order

Captured-citizen desertion and integration run before Bank interest and
liquidation. Financial effects use freshly read state after that check. Ordinary
citizen rollover and population recovery follow; midnight rollover still finishes
before combat arriving at the same timestamp. Repeated processing is idempotent.

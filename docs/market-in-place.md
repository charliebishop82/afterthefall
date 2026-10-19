# In-place market transactions

Prepared separately during the user's full run and installed after it finished. The earlier full run does not include these new market tests.

Market forms submit once through the same /market route, URL-encoded fields, session, CSRF, origin, clock and service validation. A successful request with X-Market-Async: 1 returns 204 after normal transaction and activity handling. Ordinary forms and bots retain their 303 response. No trading rules change.

market-actions.js intercepts only /market forms inside #market. It prevents duplicate submissions while pending, shows status/errors inside the menu, and never retries a trade automatically. Transport failures explicitly warn of an uncertain outcome. Successful trades request a resource-value refresh and fetch a small authenticated /api/market-panel fragment. Fragment failure cannot resend or mislabel the already-confirmed trade.

The fragment endpoint reads saved state without advancing simulation or submitting an action. The existing outer market panel and menu references remain intact; only its children change. Expanded sections, quantities clamped to fresh limits, and drawer scroll position are preserved. Equipment details use stable summary labels so changing stock counts do not collapse them. Top explanatory text stays collapsed by default.

The resource refresher coalesces immediate refresh requests with existing polling, preventing overlapping refreshes or duplicate polling timers. It does not reload the page for market transactions. Existing catch-up transitions are unchanged.

Syntax checked only; agent did not run tests. New backend tests restore one class baseline, use ordinary validated market transactions and verify no redirect, unchanged normal-form behavior, rejection/CSRF rules, and authenticated read-only fragment access. New Node tests cover one submission, headers/form encoding, rejections, uncertain outcomes, unexpected response pages, and distinct quantity-preservation keys. The full runner discovers both automatically.

After installation, run:

    python -X utf8 -m unittest tests.test_market_in_place
    node --test tests/test_market_actions.cjs

Restart only the game server and refresh the browser to load the script. Keep the existing database. No database reset or admin/bot restart is required for this change. The current full run will not include these staged tests.

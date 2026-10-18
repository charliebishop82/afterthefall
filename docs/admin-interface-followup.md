# Admin and map follow-up

The player navigation stays outside Account & help, with labelled shortcuts above the map and a fixed bottom dock. Management drawers overlay the map. Map height follows the available viewport.

Player inspection now includes bounded read-only tables for expeditions, equipment, ammunition, jobs, equipment trades and daily resource purchases. Each section shows at most 50 saved records. Inspection does not advance time. Diagnostics also check equipment-market stock and invalid transaction amounts. Existing correction safeguards remain unchanged.

Restart the player and admin servers with the same database, then hard-refresh both browsers. No tests were run for this change; Python syntax and JavaScript syntax were checked only.

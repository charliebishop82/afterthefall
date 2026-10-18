# Map-first interface overhaul — October 17, 2026

Presentation changes only. No prices, capacities, worker requirements, production,
combat, Oxygen, database or simulation rules change.

The resource bar stays fixed at the top on every settlement view. Nine compact
cells retain live quantities, storage limits/full badges, citizens/free citizens
and ground defense. Icons supplement labels. Rates are available on hover or
keyboard focus, and the Resource rates button expands all rates. Responsive rows
remain visible on smaller screens; their measured height reserves layout space.

The map is the primary workspace and stays in the DOM and visible when navigating
to Citizens, Military, Economy, Overview and Diplomacy. Management views become
closable side panels on wide screens and sliding overlay panels on small screens.
Build is the default for a new session; explicit links and saved menu selection
still work. Lists & manual controls opens the original building controls. Closing
the management panel returns to the map. Citizen/military visual boards remain;
the manual citizen roster and longer management sections are collapsed initially.

Selecting a map structure reuses the existing inspector and original form nodes,
tokens and validation. The build overlay still reuses the original construction
form, rotation, footprint placement and automatic site suggestion. Pan, zoom,
filters, build/scavenging percentages and ETA markers retain their existing code.
No new network poll, backend simulation or automatic action is introduced.

Needs attention shows the current count of resource warnings. Active work links
to the existing projects, scavenging yields/crew controls, expeditions/recall and
combat reports. Account, Help, logout and score details move into one compact menu.

Primary map purposes use labelled colours: Food green, Water blue, Oxygen teal,
Electricity amber, Industry orange, Housing cream, Military muted red, Storage
purple and Support grey-blue. Town Hall remains gold. Food/Water/Material storage
share the storage category. Secondary production does not recolour a building.
Purpose letters and the legend supplement colours. Derelicts and destroyed sites
are faded/dashed; construction keeps its primary colour with a dotted work outline.
Damage (!), missing operating workers (○) and stalled work (Ⅱ) use separate badges.
Selection adds a bright outline. Existing no-worker buildings remain exempt.

## Validation and handoff

New Python tests cover purpose mapping and new Node tests cover filtering, status
symbols and legend distinctions. They are automatically discovered by full-suite
and optional UI discovery respectively. Static parsing is not an executed test.
No tests were run by Codex. Browser visual/interaction validation remains pending
until the owner restarts the game and opens the installed interface. No visual
quality or full regression pass is claimed from source inspection alone.

Keep the current test run on its existing code until it exits; install after that.
Restart the player server with the same database, then hard-refresh the browser
(Ctrl+F5). No save reset is required. Check map placement/rotation, pan/zoom, map
selection, worker assignment/release, sidebar close/Escape, each bottom menu,
mobile wrapping, resource updates and existing confirmation dialogs.

The existing manual layout remains available without JavaScript. The previously
published PDF guide is unchanged. This map shell supplements existing scripts;
it does not remove their form fields, IDs, server routes or safeguards.

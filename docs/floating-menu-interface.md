# Map and floating management windows

The player map starts at current O2 coverage on each page load, ignoring saved camera positions. The Full map button shows the entire settlement. Zoom and pan remain available, and tiles retain their proportions. Resources, storage limits and the existing live net hourly rates remain visible at the top; these are net changes after consumption, not gross production. Credits are funds rather than a production rate. Opening menus does not change the camera.

Use the fixed bottom navigation for Overview, Build, Citizens, Economy, Military and Diplomacy. Management menus open in one labelled, scrollable floating window. Close with its Close button, Escape, or the same selected menu button. Build returns to the map; Lists & manual controls opens the building lists. Structure clicks close management and open the smaller existing structure inspector. Existing forms, game rules and update requests remain unchanged. Existing nodes preserve their content and scroll state while hidden.

The optional UI suite automatically discovers test_map_initial_camera.cjs. Tests were added but not run. JavaScript syntax checks passed. Authenticated visual inspection still needs the player's browser; only the separate guide tab was available to the coding session.

After installation, hard-refresh the player browser with Ctrl+F5. These static-file edits do not require a server restart. Save data is unchanged.


# Compact player management menus

This presentation increment applies only to non-Build player popup contents: Overview, Citizens, Economy, Military and Diplomacy. Build, the map, inspectors/placement rules and map controls retain their existing implementation and styles. New styles require the menu-refined class, which the new script never applies to screen-build. The popup window sizing class is removed whenever Build is selected.

Each popup has a labelled section navigation strip. One section is visible at a time rather than a stack of collapsed accordion headings. Economy starts on the public market, Diplomacy on treaties, Overview on alerts when present; the existing Military dashboard and Citizens portal remain. The last selected section stays selected while the page remains loaded. Existing deep links reveal the appropriate section. No original forms, action URLs, identifiers, field validation, confirmation steps or live-refresh sources are replaced.

Popups fit their content up to the available screen height, then scroll internally. Forms use compact rows, the resource market uses two columns on wider screens, and citizen/equipment cards use available columns. Small screens retain wrapping and scrolling. Rules/info disclosures remain available. Navigation uses normal labelled links with aria-current and keyboard focus styling.

Optional UI test discovery automatically includes test_menu_layout.cjs. JavaScript syntax was checked; tests were not run, and authenticated browser visual verification remains pending. Hard-refresh the player browser after restarting the player server with the same save (template references changed). No admin or bot restart is needed.

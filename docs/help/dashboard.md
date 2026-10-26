# The dashboard

## Widgets
Each widget is a query over the current version of your data. How do you know? under a widget shows the exact SQL it runs, with Copy. The menu (the three dots) changes the view, duplicates, collapses, shows it as a table or deletes it; a deleted widget can be brought back with Undo on the toast.

## Filter by clicking
Click a bar or a slice to filter every other widget to that category. Click it again, or the × on the filter chip, to clear it.

## Add a widget
Add widget opens a drawer: describe the chart in words, or start from a template (a bar of X by Y, a KPI of X, or a table). In chat on the Dashboard tab, ask "add a chart of fare by port to the dashboard". A chart answered in chat can also be pinned with Pin to dashboard.

## Arrange the dashboard
Drag a widget by its handle (the dots left of its title) to move it. Edit layout adds a resize corner to every widget and lets you drag by the whole header. The layout is saved for this file.

## Story cards
The story panel on the right has an overview card, then one card per widget, written from numbers computed in code. Every number is a chip: hover it to see what it is, and click it to see where it came from (the value, the version, and its SQL or how it was derived). Clicking a card scrolls to its widget. A card marked changed was rewritten after the data changed; click the badge to dismiss it. "outdated, click to refresh" means it waits for you to click it.

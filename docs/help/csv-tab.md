# The CSV tab

## Edit cells
Double-click a cell (or press Enter, or start typing) to edit it. Everything here can also be asked of the chat ("delete row 5", "add a row with …", "rename a column …"). Add row adds an empty row at the top; Delete row marks the rows of the selected cells. Edits stay unsaved, and are kept in this browser, until you press Save changes; Discard drops them, and the Changes panel lists each one with × to remove it. Saving makes a new version, and any analysis that read a changed column is marked Outdated. The toast after a save has Undo, and when you added rows, Clean them: it opens the cleaning plan for just those rows, and nothing is cleaned until you press Start cleaning.

## Find and sort
Use Find to search every cell: the grid then shows only the matching rows until you close the find bar (Esc or ×). Click a column header to sort by it (ascending, descending, off); sorting only changes the view, not the data. A link like "Open these rows in CSV" from chat, or Who did it get wrong? in a model card, shows only those rows; press Show all rows to see all of them again.

## The Changes panel
The right panel lists every cleaning step and every saved edit with what it changed and Undo. Expanding a step shows its code (or, for saved edits, the list of edits), its impact and its decisions. Full cleaning report and Export notebook are at the bottom.

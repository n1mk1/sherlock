# Chat and export

## Ask anything
The bar below the grid answers questions about the open file: "average fare by class", "which passengers paid over 500?", "a chart of fare by port", "is fare different between men and women?", "what drives survival?", "what does pclass mean?". Every number in an answer comes from a query that ran; click a number or How do you know? to see it. Answers come as a number, a table, a chart or text, and an answer about rows links to them in the grid. Press / to jump to the bar and Esc to close the thread. The chip on the left of the bar shows what the question applies to: all rows, or the rows you selected in the grid.

## Change the data from chat
Tell chat what to change in plain words, in any wording: "trim the spaces in name", "make fare a number", "I want sex in capitals", "fare → 2dp", "the names have extra spaces, fix them", "add family_size = sibsp + parch + 1". While it works, chat says each stage (writing the code, running it on a copy, fixing the code). Sherlock writes short pandas code, test-runs it on a copy, checks it and shows you a card: first what it understood ("Upper-case every value in sex"), then the counts ("Change 1,309 cells in 1,309 rows: sex", or "Make age whole numbers" when only the type changes), the code (long code is folded), and a before-and-after preview that shows each kind of change once, with "and N more like these". A change you ask for by name that the checks would normally stop (blanking values, filling blanks with a word like "Unknown", making different values the same, turning numbers or dates into text) gets a warning on the card instead of a refusal; a change that would mix text into a number column is still refused. When there's no card, chat says why and what to try ("This file has no column called Fare. The closest is fare."). Nothing changes until you press OK; then the change is saved (at once, if the data hasn't moved since the card) and the grid shows the new version with the changed cells marked. Cancel drops it. "Round fare, then count by sex" makes the card and asks the rest after OK. With rows selected in the grid, the change applies only to those rows. If the data changed after the card appeared, OK checks the code again on the new version, and asks once more when the effect is different. While a clean runs, OK queues the change until the clean ends. You can also change single cells by row number ("set the fare of row 9 to 30", with Approve) or clean the selected rows with AI.

## Work on the file like a spreadsheet
Chat does what you'd do to a spreadsheet by hand, each as a card you read before OK, and each undoable:
- Rows: "delete row 5", "delete these rows" (the selected ones), "delete the passengers with no age", "remove the duplicates". Deleted rows leave the file; the card says how many, warns when it's more than a fifth, and Undo brings them back. To keep rows in the file but out of answers, say "set aside" or "quarantine" instead; "bring back the set-aside rows" restores them.
- New rows: "add a row with name Jane Doe, sex female and age 30", or "add 3 blank rows". They go at the end of the file, and the card shows each one before you approve.
- Columns: "add a column notes" (a blank column), "add total = price * quantity", "delete the column cabin", "rename home.dest to destination", "move fare to the front".
- Cells: "set the fare of row 9 to 30", "replace S with Southampton in embarked", "fill missing age with the median", "round fare to 2 places", "make sex upper case".
- Sorting: "sort by fare descending" sorts the grid, as clicking the header does, and "clear the sort" puts it back in row order. Sorting changes the view, not the file.
- Finding: "show the passengers who paid over 500" opens the matching rows in the grid.

## Questions SQL can't answer
Most questions run as a query. Questions a query can't answer well (a regression, clustering, fuzzy matching of near-duplicate names, a calculation in several steps) run as pandas code instead. That code only reads the data, so no OK is needed; How do you know? shows it.

## Undo and Redo
Undo in the CSV toolbar (or Ctrl+Z) takes back the latest change, up to three in a row; Redo (Ctrl+Y) brings them back. Making a new change after an undo clears Redo. Older changes can be undone one by one in the Changes panel.

## Statistical tests
Ask whether a difference is significant and Sherlock picks the test by the column types: Welch's t-test and Mann-Whitney for a number across two groups, Kruskal-Wallis for more groups, chi-square for two categories, Pearson and Spearman for two numbers. It reports the p-value and an effect size.

## Export a notebook
The dataset menu (three dots in the header) has Export notebook. Ctrl+Shift+E, the CSV grid's Download menu, the Changes panel and asking chat to "export a notebook" open the same dialog. The notebook rebuilds your cleaned data from the raw file step by step, then reruns the analyses. In the dialog you can leave out the data or the analyses. It runs on its own in Jupyter, Colab or Kaggle.

## Settings
The gear in the library opens settings: Mode (light, dark or system), the accent colour, the chat bar (pinned, auto-hide until you point at it, or hidden), and what happens after an upload (ask me, open the cleaning plan, or I'll clean it myself; nothing is cleaned until you start a plan). Changes apply at once and are saved to your Sherlock profile.

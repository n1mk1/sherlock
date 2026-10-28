# Chat and export

## Ask anything
The bar below the grid answers questions about the open file: "average fare by class", "which passengers paid over 500?", "a chart of fare by port", "is fare different between men and women?", "what drives survival?", "what does pclass mean?". Every number in an answer comes from a query that ran; click a number or How do you know? to see it. Answers come as a number, a table, a chart or text, and an answer about rows links to them in the grid. Press / to jump to the bar and Esc to close the thread. The chip on the left of the bar shows what the question applies to: all rows, or the rows you selected in the grid.

## Change the data from chat
Tell chat what to change in plain words: "trim the spaces in name", "make fare a number", "replace NYC with New York in city", "fill missing embarked with S", "add family_size = sibsp + parch + 1". Sherlock writes the pandas code, test-runs it on a copy, checks it (no rows lost, no new blanks, column types kept) and shows you a card with the code and a before-and-after preview. Nothing changes until you press OK; then the code runs on the file and the grid shows the new version with the changed cells marked. Cancel drops it. With rows selected in the grid, the change applies only to those rows. Asking to delete rows sets them aside (quarantined) instead: they stay in the file and can be restored. If the data changed after the card appeared, OK checks the code again on the new version, and asks once more when the effect is different. While a clean runs, OK queues the change until the clean ends. You can also change single cells by row number ("set the fare of row 9 to 30", with Approve) or clean the selected rows with AI.

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

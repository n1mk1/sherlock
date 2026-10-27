# Chat and export

## Ask anything
The bar below the grid answers questions about the open file: "average fare by class", "which passengers paid over 500?", "a chart of fare by port", "is fare different between men and women?", "what drives survival?", "what does pclass mean?". Every number in an answer comes from a query that ran; click a number or How do you know? to see it. Answers come as a number, a table, a chart or text, and an answer about rows links to them in the grid. Press / to jump to the bar and Esc to close the thread. The chip on the left of the bar shows what the question applies to: all rows, or the rows you selected in the grid.

## Change the data from chat
Ask chat to change cells ("set the fare of row 9 to 30") or to clean the selected rows. A change arrives as a proposal with Approve and Reject; nothing changes until you approve, and an approved change is a step you can undo in Changes. Chat never deletes rows.

## Statistical tests
Ask whether a difference is significant and Sherlock picks the test by the column types: Welch's t-test and Mann-Whitney for a number across two groups, Kruskal-Wallis for more groups, chi-square for two categories, Pearson and Spearman for two numbers. It reports the p-value and an effect size.

## Export a notebook
The dataset menu (three dots in the header) has Export notebook. Ctrl+Shift+E, the CSV grid's Download menu, the Changes panel and asking chat to "export a notebook" open the same dialog. The notebook rebuilds your cleaned data from the raw file step by step, then reruns the analyses. In the dialog you can leave out the data or the analyses. It runs on its own in Jupyter, Colab or Kaggle.

## Settings
The gear in the library opens settings: Mode (light, dark or system), the accent colour, the chat bar (pinned, auto-hide until you point at it, or hidden), and what happens after an upload (ask me, open the cleaning plan, or I'll clean it myself; nothing is cleaned until you start a plan). Changes apply at once and are saved to your Sherlock profile.

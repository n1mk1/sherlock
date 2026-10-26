# Chat and export

## Ask anything
The bar at the bottom answers questions about the open file: "average fare by class", "which passengers paid over 500?", "is fare different between men and women?", "what drives survival?", "what does pclass mean?". Every number in an answer comes from a query that ran; How do you know? shows it. Pin to dashboard turns a chart answer into a widget, and Add to Flow puts an answer's text on the canvas as a card. Press / to jump to the bar and Esc to close the thread. The chip on the left of the bar shows what the question applies to (all rows, the dashboard filter, the widget you clicked, the selected cells on the CSV tab, or the selected cards on the Flow tab). On the Dashboard, click it to clear the filter or the widget.

## Statistical tests
Ask whether a difference is significant and Sherlock picks the test by the column types: Welch's t-test and Mann-Whitney for a number across two groups, Kruskal-Wallis for more groups, chi-square for two categories, Pearson and Spearman for two numbers. It reports the p-value and an effect size.

## Export a notebook
The dataset menu (three dots in the header) has Export notebook. Ctrl+Shift+E, the CSV tab's Download menu, the Changes panel, the Flow palette and asking chat to "export a notebook" open the same dialog. The notebook rebuilds your cleaned data from the raw file step by step, reruns every widget's query and every analysis, and includes the story cards. In the dialog you can leave out the data, the story cards or the analyses, or add the canvas notes. It runs on its own in Jupyter, Colab or Kaggle.

## Settings
The gear in the library opens settings: Mode (light, dark or system), the accent colour, the chat bar (pinned, auto-hide until you point at it, or hidden), and what happens after an upload (ask me, open the cleaning plan, or I'll clean it myself; nothing is cleaned until you start a plan). Changes apply at once and are saved to your Sherlock profile.

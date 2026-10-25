# Chat and export

## Ask anything
The bar at the bottom answers questions about the open file: "average fare by class", "which passengers paid over 500?", "is fare different between men and women?", "what drives survival?", "what does pclass mean?". Every number in an answer comes from a query that ran; How do you know? shows it. Pin to dashboard turns a chart answer into a widget.

## Statistical tests
Ask whether a difference is significant and Sherlock picks the test by the column types: Welch's t-test and Mann-Whitney for a number across two groups, Kruskal-Wallis for more groups, chi-square for two categories, Pearson and Spearman for two numbers. It reports the p-value and an effect size.

## Export a notebook
The dataset menu (three dots in the header) has Export notebook. The notebook rebuilds your cleaned data from the raw file step by step, reruns every widget's query and every analysis, and includes the story cards. It runs on its own in Jupyter, Colab or Kaggle.

## Settings
The gear in the library opens settings: light or dark mode, the accent colour, where the chat bar sits, what happens after an upload, and whether stories update automatically or ask first.

# Analysis: what drives a column

## Run "What drives this?"
Click the flask button on a widget and choose What drives this?. Pick the column to explain (the target), check the features, and press Run. Sherlock tries logistic or ridge regression, gradient boosting and a random forest on the same cross-validation folds and keeps the best. On a new dashboard it runs one for the most likely target by itself.

## Excluded columns
Columns that would give the answer away are left out and struck through with the reason: IDs, free text, dates, and columns that record the outcome (leakage). You can put one back in; the model card then warns about it.

## Baselines and the verdict
Every model is compared with two simple rules: everyone gets the most common outcome (or the average), and the best rule using a single column. The verdict says whether the model beats them on rows it never saw. "No signal" means it doesn't.

## Reading the importance
The bars show permutation importance: how much the model's score drops when a column's values are shuffled, scaled so the strongest is 1. Click a bar to see how the prediction changes as that factor changes. These are associations, not causes.

## The model card
Model card under the widget lists the rows used, the excluded columns, the method, the baselines with intervals, the importance, the warnings, and the reproduction code. For categories it also shows the confusion matrix, the ROC curve for yes/no targets, and Who did it get wrong?, which opens those rows in the CSV tab.

## Outdated analyses
When the data changes in a column the analysis used, it is marked Outdated. Re-run runs it again on the new version, or it re-runs by itself if Story updates is set to Automatic.

## What isn't here yet
Predicting a column, finding groups, finding unusual rows and forecasting are shown in the menu but not available in this release.

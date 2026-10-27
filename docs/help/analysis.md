# Analysis: what drives a column

## Run "What drives this?"
Ask in chat: "what drives survived?" (or any column's name). Sherlock explains that column (the target) from the others on the rows the question applies to: all rows, or the rows you selected in the grid. With no column named, it picks the most likely target. It tries logistic or ridge regression, gradient boosting and a random forest on the same cross-validation folds and keeps the best. The answer gives the verdict against the baselines, the strongest factors, the importance table and a link to the model card. Asking the same question again on the same data reuses the run.

## Excluded columns
Columns that would give the answer away are left out, and the model card lists each with the reason: IDs, free text, dates, and columns that record the outcome (leakage).

## Baselines and the verdict
Every model is compared with two simple rules: everyone gets the most common outcome (or the average), and the best rule using a single column. The verdict says whether the model beats them on rows it never saw. "No signal" means it doesn't.

## Reading the importance
The importance is permutation importance: how much the model's score drops when a column's values are shuffled, scaled so the strongest is 1. These are associations, not causes.

## The model card
Open it from the answer's link, or ask "tell me about the model". It lists the rows used, the excluded columns, the method, the baselines next to the model's score and its interval, the importance, the warnings, the limits, and the reproduction code (Show the code). For categories it also shows the confusion matrix, the ROC curve for yes/no targets, and Who did it get wrong?, which opens those rows in the CSV grid.

## Outdated analyses
When you save edits, undo a step or clean again, any analysis that used a changed column is marked Outdated, and chat and the model card say so. Nothing runs again by itself: press Re-run in the model card, or ask the question again in chat, to run it on the current version.

## What isn't here yet
Predicting a column, finding groups, finding unusual rows and forecasting are not available in this release.

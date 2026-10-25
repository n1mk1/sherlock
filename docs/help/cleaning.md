# Cleaning

## What the cleaner does
The cleaner works through the issues it found (spacing and case, typos in categories, numbers stored as text, dates in mixed formats, placeholders like N/A) one at a time. Each fix is code that runs in a sandbox, is checked, and becomes a step with a version of its own.

## Quarantined rows
Rows the cleaner can't trust are quarantined, not deleted. They stay in the CSV tab, struck through with the reason, and are left out of charts, answers and models. Restore brings a row back.

## Undo a step
Open the CSV tab and its Changes panel. Each step has Undo. Undoing an earlier step replays the later ones, so nothing else is lost.

## Missing values
Missing values stay missing unless a fix is clearly safe. Sherlock doesn't invent values to fill gaps.

"""Embedded outputs (TRD §7.7, PRD NB-7): table outputs computed from the app's own data at export
time, so the notebook reads correctly on GitHub and Kaggle without being run. Capped at 50 rows."""

import pandas as pd
from nbformat.v4 import new_output

MAX_ROWS = 50


def table(columns: list[dict], rows: list[list], total: int | None = None) -> dict:
    frame = pd.DataFrame(rows[:MAX_ROWS], columns=[c["name"] for c in columns])
    html = frame.to_html(index=False, border=0, na_rep="")
    text = frame.to_string(index=False, na_rep="")
    shown = min(len(rows), MAX_ROWS)
    total = total if total is not None else len(rows)
    if total > shown:
        note = f"first {shown} of {total:,} rows"
        html += f"<p>{note}</p>"
        text += f"\n({note})"
    return new_output("execute_result", data={"text/html": html, "text/plain": text}, execution_count=None)

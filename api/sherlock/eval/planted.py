"""Planted-truth data for the ML checks (PRD ML-3, TRD §14): seeded frames whose drivers are known.

- `drivers`: a two-class outcome made from `strong` (most), `moderate` and a category `group`, with
  `noise` unrelated, `leak` a copy of the outcome under another name and `code` an ID. A good run
  finds strong, then moderate, leaves out the leak and the ID, and beats the baselines.
- `noise`: the same columns with an outcome that's a coin toss. A good run reports no signal.
- `regression`: a number made from `strong` and `moderate` plus noise.
"""

import numpy as np
import pandas as pd


def _base(n: int, rng: np.random.Generator) -> pd.DataFrame:
    return pd.DataFrame({
        "code": [f"C{i:05d}" for i in range(n)],
        "strong": rng.normal(0, 1, n).round(3),
        "moderate": rng.normal(0, 1, n).round(3),
        "noise": rng.normal(0, 1, n).round(3),
        "group": rng.choice(["a", "b", "c"], n),
    })


def drivers(n: int = 800, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = _base(n, rng)
    score = 2.5 * df["strong"] + 1.0 * df["moderate"] + df["group"].map({"a": 0.6, "b": 0.0, "c": -0.6}) + rng.normal(0, 0.8, n)
    df["outcome"] = (score > 0).astype(int)
    df["leak"] = df["outcome"].map({1: "yes", 0: "no"})
    return df


def noise(n: int = 800, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = _base(n, rng)
    df["outcome"] = rng.integers(0, 2, n)
    return df


def regression(n: int = 800, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = _base(n, rng)
    df["value"] = (10 + 4 * df["strong"] + 1.5 * df["moderate"] + rng.normal(0, 1, n)).round(3)
    return df


def card_for(df: pd.DataFrame, target: str, leakage: dict | None = None) -> dict:
    """A DataCard sketch with the types and roles the profiler gives these columns."""
    cols = []
    for c in df.columns:
        s = df[c]
        if c == "code":
            cols.append({"name": c, "type": "id", "role": "id"})
        elif pd.api.types.is_float_dtype(s):
            cols.append({"name": c, "type": "float", "role": "measure"})
        elif pd.api.types.is_integer_dtype(s):
            cols.append({"name": c, "type": "int", "role": "target_like" if c == target else "dimension"})
        else:
            cols.append({"name": c, "type": "category", "role": "dimension"})
    return {"columns": cols, "target_candidates": [target],
            "leakage_candidates": [{"column": k, "target": target, "reason": v} for k, v in (leakage or {}).items()]}


def as_version(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.insert(0, "_quarantine_reason", None)
    out.insert(0, "_row_id", range(1, len(df) + 1))
    return out


CASES = [
    # (name, frame, target, expected verdict, expected top two, columns that must be left out)
    ("drivers", drivers, "outcome", "beats_baseline", ["strong", "moderate"], ["leak", "code"]),
    ("noise", noise, "outcome", "no_signal", None, ["code"]),
    ("regression", regression, "value", "beats_baseline", ["strong", "moderate"], ["code"]),
]


def run() -> str:
    """`sherlock eval ml` (TRD §14): each planted case through the analysis, as a markdown table."""
    from sherlock.ml.analysis import analyze

    lines = ["| case | model | metric | verdict | top two | left out | pass |", "|---|---|---|---|---|---|---|"]
    passed = 0
    for name, make, target, verdict, top, out in CASES:
        df = make()
        a = analyze(as_version(df), card_for(df, target), "_quarantine_reason IS NULL AND (1=1)", target)
        got_top = [i["column"] for i in a.card["importance"][:2]]
        left = [e["column"] for e in a.card["excluded"]]
        ok = a.card["verdict"] == verdict and (top is None or got_top == top) and all(c in left for c in out)
        passed += ok
        m = a.card["model"]
        lines.append(f"| {name} | {a.model} | {m['metric']} {m['value']:.3f} | {a.card['verdict']} | {', '.join(got_top)} | "
                     f"{', '.join(left)} | {'yes' if ok else 'NO'} |")
    lines.append(f"\n{passed} of {len(CASES)} planted cases pass.")
    return "\n".join(lines)

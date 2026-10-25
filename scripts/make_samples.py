"""Write the synthetic sample files (Implementation Plan §6) into api/samples/. Seeded: the same
files every run.

Run from the repo root:  uv run --project api python scripts/make_samples.py
"""

from pathlib import Path

from sherlock.eval import synthetic

OUT = Path(__file__).resolve().parents[1] / "api" / "samples"


def write_csv(df, name: str) -> None:
    path = OUT / name
    path.write_bytes(df.to_csv(index=False, lineterminator="\n").encode("utf-8"))
    print(f"wrote {path.name}: {len(df):,} rows × {len(df.columns)} columns")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    write_csv(synthetic.sales(), "sales_dated.csv")
    write_csv(synthetic.wide_messy(), "wide_messy.csv")
    write_csv(synthetic.reviews(), "reviews_text.csv")
    data = synthetic.broken_latin1()
    (OUT / "broken_latin1.txt").write_bytes(data)
    print(f"wrote broken_latin1.txt: {len(data):,} bytes, Latin-1, ';', header on row 3")

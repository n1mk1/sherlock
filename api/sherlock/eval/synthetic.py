"""Seeded synthetic data (Implementation Plan §6): the sample files and the benchmark's clean sets.

Everything here is generic test data. Nothing in the app is tuned to it (CLAUDE.md rule 4).
"""

import random
from datetime import date, timedelta

import numpy as np
import pandas as pd

REGIONS = ["North", "South", "East", "West", "Central"]
PRODUCTS = {"Widget": 12.5, "Gadget": 30.0, "Doohickey": 7.25, "Gizmo": 55.0, "Sprocket": 3.4}
DEPARTMENTS = ["Engineering", "Sales", "Marketing", "Finance", "Support", "Operations"]
CITIES = {"Zürich": "ZH", "Genève": "GE", "Lausanne": "VD", "Bern": "BE", "Basel": "BS", "Montréal": "QC",
          "Québec": "QC", "Toronto": "ON", "München": "BY", "Köln": "NW"}
FIRST = ["Ana", "Ben", "Chloé", "Dmitri", "Elif", "Farah", "Gaël", "Hiro", "Inès", "Jonas", "Kofi", "Léa",
         "Mateo", "Noor", "Oskar", "Priya", "Quinn", "René", "Sofía", "Tomás", "Uma", "Vera", "Wen", "Ximena"]
LAST = ["Müller", "Dubois", "Rossi", "Novak", "Silva", "Kim", "Okafor", "Larsen", "Haddad", "Tanaka", "García",
        "Petrov", "Nguyen", "Kowalski", "O'Brien", "Schäfer"]


def sales(rows: int = 5000, seed: int = 11) -> pd.DataFrame:
    """Monthly-dated orders over three years with a trend and a seasonal swing."""
    rng = np.random.default_rng(seed)
    start = date(2022, 1, 1)
    days = rng.integers(0, 365 * 3, rows)
    dates = [start + timedelta(days=int(d)) for d in sorted(days)]
    product = rng.choice(list(PRODUCTS), rows)
    region = rng.choice(REGIONS, rows, p=[0.3, 0.25, 0.2, 0.15, 0.1])
    season = np.array([1 + 0.3 * np.sin(2 * np.pi * d.month / 12) for d in dates])
    trend = np.linspace(1.0, 1.4, rows)
    units = np.maximum(1, rng.poisson(8 * season * trend)).astype(int)
    price = np.array([PRODUCTS[p] for p in product]) * rng.choice([1.0, 0.9, 0.8], rows, p=[0.8, 0.15, 0.05])
    return pd.DataFrame({
        "order_id": [f"SO-{100000 + i}" for i in range(rows)],
        "order_date": [d.isoformat() for d in dates],
        "region": region,
        "product": product,
        "units": units,
        "unit_price": np.round(price, 2),
        "revenue": np.round(units * price, 2),
        "returned": rng.choice(["no", "yes"], rows, p=[0.93, 0.07]),
    })


def hr(rows: int = 1200, seed: int = 23) -> pd.DataFrame:
    """Employees with a city → region dependency, accented names, salaries by department."""
    rng = np.random.default_rng(seed)
    dept = rng.choice(DEPARTMENTS, rows)
    base = {"Engineering": 98000, "Sales": 72000, "Marketing": 69000, "Finance": 85000, "Support": 52000,
            "Operations": 61000}
    city = rng.choice(list(CITIES), rows)
    hire = [date(2010, 1, 1) + timedelta(days=int(d)) for d in rng.integers(0, 365 * 14, rows)]
    age = rng.integers(22, 64, rows)
    salary = np.array([base[d] for d in dept]) * rng.normal(1.0, 0.12, rows) + (age - 22) * 400
    return pd.DataFrame({
        "employee_id": [f"E{5000 + i}" for i in range(rows)],
        "name": [f"{rng.choice(FIRST)} {rng.choice(LAST)}" for _ in range(rows)],
        "department": dept,
        "city": city,
        "region_code": [CITIES[c] for c in city],
        "hire_date": [d.isoformat() for d in hire],
        "age": age,
        "salary": np.round(salary, 0).astype(int),
        "left_company": rng.choice(["no", "yes"], rows, p=[0.85, 0.15]),
    })


CLINICS = ["Riverside", "Hillcrest", "Lakeview", "Old Town"]


def visits(rows: int = 400, seed: int = 57) -> pd.DataFrame:
    """Clinic visits whose dates all have a day of 12 or less (and never day = month), so written as
    `dd/mm/yyyy` or `mm/dd/yyyy` every one reads both ways: the benchmark's truly ambiguous dates."""
    rng = np.random.default_rng(seed)
    out = []
    while len(out) < rows:
        d = date(2021, 1, 1) + timedelta(days=int(rng.integers(0, 365 * 3)))
        if d.day <= 12 and d.day != d.month:
            out.append(d)
    clinic = rng.choice(CLINICS, rows)
    return pd.DataFrame({
        "visit_id": [f"V-{70000 + i}" for i in range(rows)],
        "visit_date": [d.isoformat() for d in out],
        "clinic": clinic,
        "minutes": rng.integers(10, 90, rows),
        "fee": np.round(rng.normal(80, 20, rows).clip(20), 2),
    })


def lookalikes(rows: int = 600, seed: int = 61) -> pd.DataFrame:
    """Members whose categories look alike but are different on purpose: "Plan A"/"Plan B",
    "Region 1"/"Region 2", and two common countries a typo apart ("Austria"/"Australia")."""
    rng = np.random.default_rng(seed)
    plan = rng.choice(["Plan A", "Plan B", "Plan C"], rows, p=[0.45, 0.35, 0.2])
    fee = {"Plan A": 19.0, "Plan B": 29.0, "Plan C": 49.0}
    return pd.DataFrame({
        "member_id": [f"M{30000 + i}" for i in range(rows)],
        "plan": plan,
        "region": rng.choice(["Region 1", "Region 2", "Region 3", "Region 4"], rows, p=[0.3, 0.3, 0.25, 0.15]),
        "country": rng.choice(["Austria", "Australia", "Canada", "Slovenia"], rows, p=[0.3, 0.3, 0.25, 0.15]),
        "monthly_fee": np.array([fee[x] for x in plan]),
        "visits": rng.integers(0, 30, rows),
    })


def titanic_clean(path) -> pd.DataFrame:
    """The sample's complete rows on its plain columns: a clean set with real distributions."""
    df = pd.read_csv(path)
    cols = ["pclass", "survived", "sex", "age", "sibsp", "parch", "fare", "embarked"]
    return df[cols].dropna().reset_index(drop=True)


def wide_messy(rows: int = 800, seed: int = 31) -> pd.DataFrame:
    """60 columns with mixed formats and placeholders (Implementation Plan §6)."""
    rng = random.Random(seed)
    data: dict[str, list] = {}
    for i in range(60):
        kind = i % 6
        name = f"{['metric', 'score', 'label', 'when', 'amount', 'note'][kind]}_{i}"
        col = []
        for _ in range(rows):
            if kind == 0:
                v = str(round(rng.gauss(100, 15), 2))
            elif kind == 1:
                v = str(rng.randint(0, 10))
            elif kind == 2:
                v = rng.choice(["alpha", "Alpha ", "beta", "BETA", "gamma"])
            elif kind == 3:
                d = date(2023, 1, 1) + timedelta(days=rng.randint(0, 600))
                v = d.strftime(rng.choice(["%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d"]))
            elif kind == 4:
                v = rng.choice(["$1,200", "980", "€45,50", "1 250", "300"])
            else:
                v = rng.choice(["ok", "check later", "", "n/a", "see notes"])
            if rng.random() < 0.04:
                v = rng.choice(["N/A", "-999", "?", ""])
            col.append(v)
        data[name] = col
    return pd.DataFrame(data)


REVIEW_BITS = ["arrived late", "works great", "battery died after a week", "excellent value",
               "would not buy again", "the support team was helpful", "packaging was damaged",
               "exactly as described", "too small for me", "five stars, no complaints"]


def reviews(rows: int = 600, seed: int = 41) -> pd.DataFrame:
    """Product reviews with a free-text column (Implementation Plan §6)."""
    rng = random.Random(seed)
    out = []
    for i in range(rows):
        rating = rng.choice([1, 2, 3, 4, 5, 5, 4])
        text = ", ".join(rng.sample(REVIEW_BITS, rng.randint(2, 4))).capitalize() + "."
        out.append({"review_id": f"R{10000 + i}", "product": rng.choice(list(PRODUCTS)), "rating": rating,
                    "review": text, "verified": rng.choice(["true", "false", "true"]),
                    "posted": (date(2024, 1, 1) + timedelta(days=rng.randint(0, 300))).isoformat()})
    return pd.DataFrame(out)


def broken_latin1(seed: int = 51) -> bytes:
    """Semicolon-delimited Latin-1 text with two lines of preamble before the header (header on row 3)."""
    df = hr(rows=150, seed=seed)[["employee_id", "name", "city", "salary"]]
    lines = ["Personalbericht;;;", "exportiert;2024-05-01;;", ";".join(df.columns)]
    lines += [";".join(str(v) for v in row) for row in df.itertuples(index=False)]
    return ("\n".join(lines) + "\n").encode("latin-1", errors="replace")

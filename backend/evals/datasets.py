"""Deterministic evaluation datasets with planted, known facts.

* sales: the shipped sample (data/samples/sales.csv). Q3 2024 revenue falls versus Q2, mostly in
  the West region and for Standing Desks.
* support_tickets: email tickets take far longer to resolve; satisfaction falls as resolution
  time grows; about 15% of satisfaction scores are missing.
* employees: salaries differ by department; a few extreme salaries; there is no attrition data.

Ground truth is never stored: each case computes it from these frames with pandas.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import cache
from pathlib import Path

import numpy as np
import pandas as pd

SALES_CSV = Path(__file__).resolve().parents[2] / "data" / "samples" / "sales.csv"


def _csv(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, lineterminator="\n").encode()


@cache
def support_tickets() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows = []
    start = datetime(2024, 1, 1)
    hours = {"chat": 3.0, "phone": 6.0, "email": 30.0}
    for i in range(1_500):
        channel = str(rng.choice(["chat", "phone", "email"], p=[0.45, 0.3, 0.25]))
        priority = str(rng.choice(["low", "medium", "high"], p=[0.5, 0.35, 0.15]))
        resolution = float(rng.gamma(2.0, hours[channel] / 2.0)) * (
            0.6 if priority == "high" else 1.0
        )
        score = 5.0 - min(resolution / 15.0, 3.5) + rng.normal(0, 0.5)
        satisfaction: float | None = float(np.clip(round(score), 1, 5))
        if rng.random() < 0.15:
            satisfaction = None
        rows.append(
            {
                "Ticket ID": f"T-{i + 1:05d}",
                "Created At": (start + timedelta(hours=int(rng.integers(0, 24 * 300)))).isoformat(
                    sep=" "
                ),
                "Channel": channel,
                "Priority": priority,
                "Team": str(rng.choice(["Billing", "Technical", "Accounts"])),
                "Resolution Hours": round(resolution, 2),
                "Satisfaction": satisfaction,
            }
        )
    return pd.DataFrame(rows)


@cache
def employees() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    base = {"Engineering": 120_000, "Sales": 85_000, "Support": 60_000, "Finance": 95_000}
    rows = []
    for i in range(400):
        department = str(rng.choice(list(base), p=[0.35, 0.3, 0.2, 0.15]))
        tenure = float(np.clip(rng.gamma(2.0, 2.0), 0.2, 25))
        salary = base[department] * (1 + 0.03 * tenure) * float(rng.normal(1, 0.08))
        rows.append(
            {
                "Employee ID": f"E{i + 1:04d}",
                "Department": department,
                "Tenure Years": round(tenure, 1),
                "Salary": round(salary, -2),
                "Performance Score": int(rng.integers(1, 6)),
            }
        )
    frame = pd.DataFrame(rows)
    # Three planted extreme salaries (executives recorded in the same table).
    frame.loc[[5, 120, 333], "Salary"] = [610_000.0, 585_000.0, 720_000.0]
    return frame


@cache
def sales() -> pd.DataFrame:
    return pd.read_csv(SALES_CSV, parse_dates=["Order Date"])


def frames() -> dict[str, pd.DataFrame]:
    return {"sales": sales(), "support_tickets": support_tickets(), "employees": employees()}


def csv_bytes(name: str) -> bytes:
    if name == "sales":
        return SALES_CSV.read_bytes()
    return _csv({"support_tickets": support_tickets, "employees": employees}[name]())

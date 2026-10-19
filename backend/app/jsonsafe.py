"""Convert values from pandas / Arrow / DuckDB into JSON-safe Python values."""

from __future__ import annotations

import datetime as dt
import math
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

JsonScalar = None | bool | int | float | str


def to_json_value(value: Any) -> JsonScalar:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, bool | np.bool_):
        return bool(value)
    if isinstance(value, int | np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, Decimal):
        return to_json_value(float(value))
    if isinstance(value, str):
        return value
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta | pd.Timedelta):
        return str(value)
    return str(value)


def rows_to_json(rows: list[tuple[Any, ...]] | list[list[Any]]) -> list[list[JsonScalar]]:
    return [[to_json_value(value) for value in row] for row in rows]

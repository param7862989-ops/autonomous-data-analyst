"""Generate the synthetic sample dataset ``sales.csv`` (deterministic, no real data).

Story built into the data, so analyses have a known answer:

* Orders from 2023-01-01 to 2024-12-31 across four regions and six products.
* In Q3 2024 (July-September) revenue falls versus Q2 2024. Two causes are planted:
  - the West region receives about 70% fewer orders than usual, and
  - Standing Desk orders fall by about 40% in every region.
* A few values are missing (discount, sales_channel) to exercise data-quality handling.

Run from the repository root:  uv run --project backend python data/samples/generate_sales.py
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20241001
OUTPUT = Path(__file__).with_name("sales.csv")

REGIONS = {"North": 1.0, "South": 0.9, "East": 1.1, "West": 1.0}
PRODUCTS = {
    # product: (category, base unit price)
    "Laptop Pro": ("Electronics", 1299.0),
    "Wireless Mouse": ("Electronics", 39.0),
    "Monitor 27in": ("Electronics", 329.0),
    "Standing Desk": ("Furniture", 549.0),
    "Office Chair": ("Furniture", 249.0),
    "Notebook Pack": ("Office Supplies", 12.0),
}
PRODUCT_WEIGHTS = np.array([0.12, 0.22, 0.14, 0.14, 0.16, 0.22])


def in_q3_2024(day: date) -> bool:
    return date(2024, 7, 1) <= day <= date(2024, 9, 30)


def generate(seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    order_number = 1
    day = date(2023, 1, 1)
    products = list(PRODUCTS)
    while day <= date(2024, 12, 31):
        # Mild seasonality: busier in Q4.
        base_orders = 10.0 + (2.0 if day.month >= 10 else 0.0)
        for region, weight in REGIONS.items():
            expected = base_orders * weight / len(REGIONS)
            if region == "West" and in_q3_2024(day):
                expected *= 0.3
            for _ in range(rng.poisson(expected)):
                product = products[rng.choice(len(products), p=PRODUCT_WEIGHTS)]
                if product == "Standing Desk" and in_q3_2024(day) and rng.random() < 0.4:
                    continue
                category, price = PRODUCTS[product]
                # Laptops sell one or two at a time; this keeps quarter totals from being
                # dominated by a handful of large laptop orders.
                max_units = 2 if product == "Laptop Pro" else 5
                units = int(rng.integers(1, max_units + 1))
                discount = float(rng.choice([0.0, 0.0, 0.05, 0.1, 0.15]))
                unit_price = round(price * float(rng.uniform(0.95, 1.05)), 2)
                revenue = round(units * unit_price * (1 - discount), 2)
                rows.append(
                    {
                        "Order ID": f"ORD-{order_number:05d}",
                        "Order Date": day.isoformat(),
                        "Region": region,
                        "Product": product,
                        "Category": category,
                        "Sales Channel": "Online" if rng.random() < 0.55 else "Retail",
                        "Units": units,
                        "Unit Price": unit_price,
                        "Discount": discount,
                        "Revenue": revenue,
                    }
                )
                order_number += 1
        day += timedelta(days=1)

    frame = pd.DataFrame(rows)
    # Plant a small amount of missing data.
    missing_discount = rng.random(len(frame)) < 0.02
    frame.loc[missing_discount, "Discount"] = np.nan
    missing_channel = rng.random(len(frame)) < 0.01
    frame.loc[missing_channel, "Sales Channel"] = ""
    return frame


if __name__ == "__main__":
    data = generate()
    data.to_csv(OUTPUT, index=False, lineterminator="\n")
    print(f"Wrote {len(data):,} rows to {OUTPUT}")

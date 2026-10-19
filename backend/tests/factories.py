"""Builders for test files (CSV / XLSX bytes)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from openpyxl import Workbook

if TYPE_CHECKING:
    from app.analytics.operations import DatasetSchema

SAMPLE_SALES = Path(__file__).resolve().parents[2] / "data" / "samples" / "sales.csv"


def csv_bytes(text: str, encoding: str = "utf-8") -> bytes:
    return text.encode(encoding)


def xlsx_bytes(sheets: dict[str, list[list[Any]]]) -> bytes:
    workbook = Workbook()
    default = workbook.active
    for index, (title, rows) in enumerate(sheets.items()):
        sheet = default if index == 0 else workbook.create_sheet()
        assert sheet is not None
        sheet.title = title
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def add_zip_entry(data: bytes, name: str, content: bytes) -> bytes:
    buffer = io.BytesIO(data)
    with zipfile.ZipFile(buffer, "a") as archive:
        archive.writestr(name, content)
    return buffer.getvalue()


def load_dataset(csv: bytes, directory: Path) -> tuple[Path, DatasetSchema]:
    """Run the real ingestion pipeline and write the result where the engine can load it."""
    from app.analytics.operations import ColumnSpec, DatasetSchema
    from app.datasets.inference import infer_table
    from app.datasets.ingest import IngestLimits, read_csv

    raw = read_csv(csv, IngestLimits(1_000_000, 100, 50_000_000, 1))
    typed = infer_table(raw.headers, raw.frame)
    path = directory / "dataset.parquet"
    typed.frame.to_parquet(path, index=False)
    schema = DatasetSchema(
        [ColumnSpec(c.name, c.semantic_type, c.original_name) for c in typed.columns]
    )
    return path, schema

"""Builders for test files (CSV / XLSX bytes)."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

from openpyxl import Workbook

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

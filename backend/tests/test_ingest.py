from __future__ import annotations

import datetime as dt
import io
import time
import zipfile

import pytest

from app.datasets.ingest import (
    DatasetFileError,
    IngestLimits,
    detect_format,
    list_sheets,
    parse_upload,
    read_csv,
    read_xlsx,
)
from app.errors import PayloadTooLargeError
from tests.factories import add_zip_entry, csv_bytes, xlsx_bytes

LIMITS = IngestLimits(
    max_rows=1_000, max_columns=20, max_cells=10_000, max_xlsx_uncompressed_bytes=5_000_000
)


def error_code(excinfo: pytest.ExceptionInfo[DatasetFileError]) -> str:
    return excinfo.value.code


# --- format detection -----------------------------------------------------------------------


def test_detect_csv_and_xlsx() -> None:
    assert detect_format("data.CSV", b"a,b\n") == "csv"
    assert detect_format("data.tsv", b"a\tb\n") == "csv"
    assert detect_format("book.xlsx", b"PK\x03\x04rest") == "xlsx"


@pytest.mark.parametrize(
    ("filename", "head", "code"),
    [
        ("book.xls", b"\xd0\xcf\x11\xe0", "unsupported_file_type"),
        ("book.xlsm", b"PK\x03\x04", "unsupported_file_type"),
        ("image.png", b"\x89PNG", "unsupported_file_type"),
        ("noext", b"a,b", "unsupported_file_type"),
        ("book.xlsx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "unsupported_file_type"),
        ("book.xlsx", b"a,b\n1,2", "file_type_mismatch"),
        ("data.csv", b"PK\x03\x04", "file_type_mismatch"),
    ],
)
def test_detect_rejects_wrong_types(filename: str, head: bytes, code: str) -> None:
    with pytest.raises(DatasetFileError) as excinfo:
        detect_format(filename, head)
    assert error_code(excinfo) == code


# --- CSV ------------------------------------------------------------------------------------


def test_csv_basic_with_bom_and_crlf() -> None:
    table = read_csv(b"\xef\xbb\xbfname,value\r\nA,1\r\nB,2\r\n", LIMITS)
    assert table.headers == ["name", "value"]
    assert table.frame.shape == (2, 2)
    assert table.encoding == "utf-8"
    assert table.notes == []


@pytest.mark.parametrize("delimiter", [";", "\t", "|"])
def test_csv_delimiter_is_sniffed(delimiter: str) -> None:
    text = delimiter.join(["a", "b", "c"]) + "\n" + delimiter.join(["1", "2,5", "x"]) + "\n"
    table = read_csv(csv_bytes(text), LIMITS)
    assert table.delimiter == delimiter
    assert table.headers == ["a", "b", "c"]
    assert table.frame.iloc[0].tolist() == ["1", "2,5", "x"]


def test_csv_windows_1252_fallback_is_reported() -> None:
    table = read_csv("city\nSão Paulo\nZürich\n".encode("cp1252"), LIMITS)
    assert table.encoding == "windows-1252"
    assert table.frame[0].tolist() == ["São Paulo", "Zürich"]
    assert [note.code for note in table.notes] == ["encoding_fallback"]


def test_csv_utf16_with_bom() -> None:
    table = read_csv("a,b\n1,2\n".encode("utf-16"), LIMITS)
    assert table.headers == ["a", "b"]


def test_csv_quoted_fields_with_delimiters_and_newlines() -> None:
    table = read_csv(b'name,note\n"Smith, J","line one\nline two"\n', LIMITS)
    assert table.frame.iloc[0].tolist() == ["Smith, J", "line one\nline two"]


@pytest.mark.parametrize("data", [b"", b"   \n\n  "])
def test_csv_empty(data: bytes) -> None:
    with pytest.raises(DatasetFileError) as excinfo:
        read_csv(data, LIMITS)
    assert error_code(excinfo) == "empty_file"


def test_csv_header_only() -> None:
    with pytest.raises(DatasetFileError) as excinfo:
        read_csv(b"a,b,c\n", LIMITS)
    assert error_code(excinfo) == "no_data_rows"


def test_csv_ragged_row_reports_line() -> None:
    with pytest.raises(DatasetFileError) as excinfo:
        read_csv(b"a,b\n1,2\n3,4,5\n", LIMITS)
    assert error_code(excinfo) == "malformed_file"
    assert "Line 3" in excinfo.value.message


def test_csv_binary_content_rejected() -> None:
    with pytest.raises(DatasetFileError) as excinfo:
        read_csv(b"a,b\n1,\x00\x01\x02\n", LIMITS)
    assert error_code(excinfo) == "file_type_mismatch"


def test_csv_row_limit() -> None:
    limits = IngestLimits(max_rows=3, max_columns=5, max_cells=100, max_xlsx_uncompressed_bytes=1)
    read_csv(b"a\n1\n2\n3\n", limits)  # exactly at the limit is fine
    with pytest.raises(DatasetFileError) as excinfo:
        read_csv(b"a\n1\n2\n3\n4\n", limits)
    assert error_code(excinfo) == "too_many_rows"


def test_csv_column_and_cell_limits() -> None:
    wide = ",".join(f"c{i}" for i in range(21)) + "\n" + ",".join("1" * 21) + "\n"
    with pytest.raises(DatasetFileError) as excinfo:
        read_csv(wide.encode(), LIMITS)
    assert error_code(excinfo) == "too_many_columns"

    limits = IngestLimits(max_rows=100, max_columns=10, max_cells=20, max_xlsx_uncompressed_bytes=1)
    rows = "a,b,c\n" + "1,2,3\n" * 7
    with pytest.raises(DatasetFileError) as excinfo:
        read_csv(rows.encode(), limits)
    assert error_code(excinfo) == "too_many_cells"


def test_csv_formula_text_is_kept_as_text() -> None:
    table = read_csv(b'a\n"=HYPERLINK(""http://x"")"\n', LIMITS)
    assert table.frame.iloc[0, 0] == '=HYPERLINK("http://x")'


# --- XLSX -----------------------------------------------------------------------------------


def test_xlsx_single_sheet_with_native_types() -> None:
    data = xlsx_bytes(
        {"Sales": [["Date", "Amount", "Paid"], [dt.datetime(2024, 1, 5), 10.5, True]]}
    )
    table = read_xlsx(data, None, LIMITS)
    assert table.sheet_name == "Sales"
    assert table.headers == ["Date", "Amount", "Paid"]
    assert table.frame.iloc[0].tolist() == [dt.datetime(2024, 1, 5), 10.5, True]


def test_xlsx_multiple_sheets_require_selection() -> None:
    data = xlsx_bytes({"Q1": [["a"], [1]], "Q2": [["a"], [2]]})
    assert list_sheets(data, LIMITS) == ["Q1", "Q2"]
    with pytest.raises(DatasetFileError) as excinfo:
        read_xlsx(data, None, LIMITS)
    assert error_code(excinfo) == "sheet_required"
    assert excinfo.value.details == {"sheets": ["Q1", "Q2"]}
    assert read_xlsx(data, "Q2", LIMITS).frame.iloc[0, 0] == 2


def test_xlsx_unknown_sheet() -> None:
    data = xlsx_bytes({"Only": [["a"], [1]]})
    with pytest.raises(DatasetFileError) as excinfo:
        read_xlsx(data, "Missing", LIMITS)
    assert error_code(excinfo) == "sheet_not_found"


def test_xlsx_formulas_are_never_evaluated() -> None:
    # openpyxl writes formulas without cached results; data_only mode reads the cached value
    # (none), so the formula is neither executed nor returned as text.
    data = xlsx_bytes({"S": [["a", "b"], [1, "=1+1"], [2, '=WEBSERVICE("http://x")']]})
    table = read_xlsx(data, None, LIMITS)
    assert table.frame[1].tolist() == [None, None]


def test_xlsx_leading_and_interior_empty_rows() -> None:
    data = xlsx_bytes({"S": [[None, None], ["a", "b"], [1, 2], [None, None], [3, 4]]})
    table = read_xlsx(data, None, LIMITS)
    assert table.headers == ["a", "b"]
    assert table.frame.values.tolist() == [[1, 2], [3, 4]]


def test_xlsx_values_without_header_are_ignored() -> None:
    data = xlsx_bytes({"S": [["a", "b"], [1, 2, "stray note"]]})
    table = read_xlsx(data, None, LIMITS)
    assert table.frame.shape == (1, 2)


def test_xlsx_empty_sheet() -> None:
    with pytest.raises(DatasetFileError) as excinfo:
        read_xlsx(xlsx_bytes({"S": []}), None, LIMITS)
    assert error_code(excinfo) == "empty_file"


def test_xlsx_macro_enabled_content_rejected() -> None:
    data = add_zip_entry(xlsx_bytes({"S": [["a"], [1]]}), "xl/vbaProject.bin", b"\x00" * 10)
    with pytest.raises(DatasetFileError) as excinfo:
        read_xlsx(data, None, LIMITS)
    assert error_code(excinfo) == "unsupported_file_type"


def test_xlsx_zip_bomb_rejected_before_parsing() -> None:
    bomb = add_zip_entry(xlsx_bytes({"S": [["a"], [1]]}), "xl/media/padding.bin", b"0" * 6_000_000)
    with pytest.raises(PayloadTooLargeError):
        read_xlsx(bomb, None, LIMITS)


def test_xlsx_damaged_archive() -> None:
    with pytest.raises(DatasetFileError) as excinfo:
        parse_upload("book.xlsx", b"PK\x03\x04" + b"\x00" * 100, None, LIMITS)
    assert error_code(excinfo) == "malformed_file"


def test_zip_that_is_not_a_workbook() -> None:
    data = add_zip_entry(b"", "readme.txt", b"hello")
    with pytest.raises(DatasetFileError) as excinfo:
        parse_upload("book.xlsx", data, None, LIMITS)
    assert error_code(excinfo) == "file_type_mismatch"


def test_xlsx_row_limit() -> None:
    limits = IngestLimits(
        max_rows=2, max_columns=5, max_cells=100, max_xlsx_uncompressed_bytes=10**7
    )
    data = xlsx_bytes({"S": [["a"], [1], [2], [3]]})
    with pytest.raises(DatasetFileError) as excinfo:
        read_xlsx(data, None, limits)
    assert error_code(excinfo) == "too_many_rows"


def test_csv_very_wide_header_is_rejected_before_parsing() -> None:
    # 100,000 empty fields: 100 KB on disk, very expensive as a DataFrame.
    data = ("a," * 100_000 + "a\n" + "1," * 100_000 + "1\n").encode()
    started = time.perf_counter()
    with pytest.raises(DatasetFileError) as excinfo:
        read_csv(data, LIMITS)
    assert error_code(excinfo) == "too_many_columns"
    assert time.perf_counter() - started < 2


def test_xlsx_phantom_rows_are_bounded() -> None:
    # A row numbered 10 million makes openpyxl yield ~10 million empty rows from a tiny file.
    data = xlsx_bytes({"S": [["a", "b"], [1, 2]]})
    buffer = io.BytesIO(data)
    with zipfile.ZipFile(buffer) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    sheet = parts["xl/worksheets/sheet1.xml"].decode()
    sheet = sheet.replace('<row r="2"', '<row r="10000000"').replace('r="A2"', 'r="A10000000"')
    sheet = sheet.replace('r="B2"', 'r="B10000000"').replace('ref="A1:B2"', 'ref="A1:B10000000"')
    parts["xl/worksheets/sheet1.xml"] = sheet.encode()
    rebuilt = io.BytesIO()
    with zipfile.ZipFile(rebuilt, "w") as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    started = time.perf_counter()
    with pytest.raises(DatasetFileError) as excinfo:
        read_xlsx(rebuilt.getvalue(), None, LIMITS)
    assert error_code(excinfo) == "too_many_rows"
    assert time.perf_counter() - started < 5

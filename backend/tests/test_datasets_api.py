from __future__ import annotations

import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.db.models import Dataset, User
from app.main import create_app
from tests.conftest import CSRF_HEADERS, make_settings, new_client, register
from tests.factories import SAMPLE_SALES, xlsx_bytes

CSV = b"Region,Revenue,Order Date\nNorth,100.5,2024-01-01\nSouth,,2024-01-02\nNorth,50,2024-02-01\n"


def upload(
    client: TestClient,
    content: bytes = CSV,
    filename: str = "sales.csv",
    **form: str,
) -> dict:  # type: ignore[type-arg]
    response = client.post(
        "/api/datasets",
        files={"file": (filename, content, "application/octet-stream")},
        data=form,
    )
    return {"status": response.status_code, "body": response.json()}


def test_upload_csv_returns_profile(db_client: TestClient) -> None:
    register(db_client)
    result = upload(db_client)
    assert result["status"] == 201
    body = result["body"]
    assert body["name"] == "sales"
    assert body["file_format"] == "csv"
    assert (body["row_count"], body["column_count"]) == (3, 3)
    assert [c["name"] for c in body["columns"]] == ["region", "revenue", "order_date"]
    assert [c["original_name"] for c in body["columns"]] == ["Region", "Revenue", "Order Date"]
    revenue = body["profile"]["columns"][1]
    assert revenue["semantic_type"] == "numeric"
    assert revenue["missing_count"] == 1
    assert revenue["numeric"]["sum"] == 150.5


def test_upload_sample_sales_dataset(db_client: TestClient) -> None:
    register(db_client)
    result = upload(db_client, SAMPLE_SALES.read_bytes(), "sales.csv", name="Sales 2023-2024")
    assert result["status"] == 201
    assert result["body"]["name"] == "Sales 2023-2024"
    assert result["body"]["row_count"] == 7620


def test_list_get_preview_delete(db_client: TestClient, settings_storage: Path) -> None:
    register(db_client)
    first = upload(db_client, filename="first.csv")["body"]
    second = upload(db_client, filename="second.csv")["body"]

    listing = db_client.get("/api/datasets").json()
    assert listing["total"] == 2
    assert [item["id"] for item in listing["items"]] == [second["id"], first["id"]]
    page = db_client.get("/api/datasets", params={"limit": 1, "offset": 1}).json()
    assert [item["id"] for item in page["items"]] == [first["id"]]

    detail = db_client.get(f"/api/datasets/{first['id']}").json()
    assert detail["profile"]["row_count"] == 3

    preview = db_client.get(f"/api/datasets/{first['id']}/preview", params={"limit": 2}).json()
    assert preview["columns"] == ["region", "revenue", "order_date"]
    assert preview["rows"] == [
        ["North", 100.5, "2024-01-01T00:00:00"],
        ["South", None, "2024-01-02T00:00:00"],
    ]
    assert preview["total_rows"] == 3
    offset = db_client.get(f"/api/datasets/{first['id']}/preview", params={"offset": 2}).json()
    assert offset["rows"] == [["North", 50.0, "2024-02-01T00:00:00"]]

    files_before = list(settings_storage.rglob("*.parquet"))
    assert len(files_before) == 2
    assert db_client.delete(f"/api/datasets/{first['id']}").status_code == 204
    assert db_client.get(f"/api/datasets/{first['id']}").status_code == 404
    assert len(list(settings_storage.rglob("*.parquet"))) == 1


def test_xlsx_sheet_selection_flow(db_client: TestClient) -> None:
    register(db_client)
    workbook = xlsx_bytes({"2023": [["a", "b"], [1, 2]], "2024": [["a", "b"], [3, 4], [5, 6]]})
    first = upload(db_client, workbook, "book.xlsx")
    assert first["status"] == 422
    assert first["body"]["error"]["code"] == "sheet_required"
    assert first["body"]["error"]["details"]["sheets"] == ["2023", "2024"]

    second = upload(db_client, workbook, "book.xlsx", sheet_name="2024")
    assert second["status"] == 201
    assert second["body"]["sheet_name"] == "2024"
    assert second["body"]["name"] == "book (2024)"
    assert second["body"]["row_count"] == 2


def test_invalid_files_return_clear_errors(db_client: TestClient) -> None:
    register(db_client)
    cases = {
        ("empty.csv", b""): "empty_file",
        ("bad.csv", b"a,b\n1,2\n3,4,5\n"): "malformed_file",
        ("image.png", b"\x89PNG\r\n"): "unsupported_file_type",
        ("fake.xlsx", b"a,b\n1,2\n"): "file_type_mismatch",
    }
    for (filename, content), code in cases.items():
        result = upload(db_client, content, filename)
        assert result["status"] == 422, filename
        assert result["body"]["error"]["code"] == code, filename


def test_filename_is_display_only(db_client: TestClient, db_engine: Engine) -> None:
    register(db_client)
    body = upload(db_client, filename="../../etc/passwd.csv")["body"]
    assert body["original_filename"] == "passwd.csv"
    with Session(db_engine) as db:
        dataset = db.scalars(select(Dataset)).one()
    assert dataset.storage_key.startswith("datasets/")
    assert ".." not in dataset.storage_key


def test_datasets_require_authentication(db_client: TestClient) -> None:
    assert db_client.get("/api/datasets").status_code == 401
    assert upload(db_client)["status"] == 401
    assert db_client.get(f"/api/datasets/{uuid.uuid4()}").status_code == 401


def test_users_cannot_see_each_others_datasets(db_client: TestClient) -> None:
    register(db_client, email="owner@example.com")
    owned = upload(db_client)["body"]["id"]

    intruder = new_client(db_client.app)
    register(intruder, email="intruder@example.com")
    assert intruder.get("/api/datasets").json()["total"] == 0
    for path in (f"/api/datasets/{owned}", f"/api/datasets/{owned}/preview"):
        response = intruder.get(path)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    assert intruder.delete(f"/api/datasets/{owned}").status_code == 404
    # The owner still has it.
    assert db_client.get(f"/api/datasets/{owned}").status_code == 200


def test_unknown_and_malformed_ids(db_client: TestClient) -> None:
    register(db_client)
    assert db_client.get(f"/api/datasets/{uuid.uuid4()}").status_code == 404
    assert db_client.get("/api/datasets/not-a-uuid").status_code == 422


def test_file_over_upload_limit_is_rejected(db_engine: Engine, tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, max_upload_bytes=2048))
    with TestClient(app, headers=CSRF_HEADERS) as client:
        register(client)
        result = upload(client, b"a\n" + b"1\n" * 4096)
    assert result["status"] == 413
    assert result["body"]["error"]["code"] == "file_too_large"


def test_oversized_body_is_cut_off_before_parsing(db_engine: Engine, tmp_path: Path) -> None:
    # Beyond the upload limit plus multipart overhead, the middleware rejects the request
    # before the multipart parser spools anything.
    app = create_app(make_settings(tmp_path, max_upload_bytes=2048))
    with TestClient(app, headers=CSRF_HEADERS) as client:
        register(client)
        result = upload(client, b"a\n" + b"1\n" * 100_000)
    assert result["status"] == 413
    assert result["body"]["error"]["code"] == "payload_too_large"


def test_json_body_limit(db_engine: Engine, tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, max_request_body_bytes=1024))
    with TestClient(app, headers=CSRF_HEADERS) as client:
        response = client.post(
            "/api/auth/login", json={"email": "a@example.com", "password": "x" * 5000}
        )
    assert response.status_code == 413


def test_dataset_quota(db_engine: Engine, tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, max_datasets_per_user=1))
    with TestClient(app, headers=CSRF_HEADERS) as client:
        register(client)
        assert upload(client)["status"] == 201
        result = upload(client)
    assert result["status"] == 409
    assert result["body"]["error"]["code"] == "dataset_quota_exceeded"


def test_upload_rate_limit(db_engine: Engine, tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path, uploads_per_user_per_hour=1))
    with TestClient(app, headers=CSRF_HEADERS) as client:
        register(client)
        assert upload(client)["status"] == 201
        assert upload(client)["status"] == 429


def test_deleting_user_cascades_to_datasets(db_client: TestClient, db_engine: Engine) -> None:
    register(db_client)
    upload(db_client)
    with Session(db_engine) as db:
        db.delete(db.scalars(select(User)).one())
        db.commit()
        assert db.scalars(select(Dataset)).all() == []


def test_upload_limits_endpoint(db_client: TestClient) -> None:
    assert db_client.get("/api/datasets/limits").status_code == 401
    register(db_client)
    limits = db_client.get("/api/datasets/limits").json()
    assert limits["max_upload_bytes"] == 25 * 1024 * 1024
    assert ".xlsx" in limits["accepted_extensions"]

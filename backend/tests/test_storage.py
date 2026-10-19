from __future__ import annotations

import uuid
from pathlib import Path

import pandas as pd
import pytest

from app.datasets import storage as storage_module
from app.datasets.service import display_filename
from app.datasets.storage import DatasetStorage, StorageError


@pytest.fixture
def storage(tmp_path: Path) -> DatasetStorage:
    return DatasetStorage(tmp_path / "store")


def test_key_is_derived_from_ids_only(storage: DatasetStorage) -> None:
    user, dataset = uuid.uuid4(), uuid.uuid4()
    key = storage.key_for(user, dataset)
    assert key == f"datasets/{user}/{dataset}.parquet"
    assert storage.path_for(key).is_relative_to(storage.root)


@pytest.mark.parametrize(
    "key",
    [
        "../secrets.parquet",
        "datasets/../../etc/passwd",
        "/etc/passwd",
        "datasets/not-a-uuid/also-not.parquet",
        f"datasets/{uuid.uuid4()}/{uuid.uuid4()}.parquet/../../x",
        f"datasets/{uuid.uuid4()}/{uuid.uuid4()}.csv",
    ],
)
def test_invalid_keys_are_rejected(storage: DatasetStorage, key: str) -> None:
    with pytest.raises(StorageError):
        storage.path_for(key)


def test_write_read_delete_roundtrip(storage: DatasetStorage) -> None:
    key = storage.key_for(uuid.uuid4(), uuid.uuid4())
    frame = pd.DataFrame({"a": pd.array([1, None, 3], dtype="Int64"), "b": ["x", "y", None]})
    size = storage.write_frame(key, frame)
    assert size > 0
    assert storage.exists(key)
    assert storage.read_rows(key, 0, 10).to_pylist() == [
        {"a": 1, "b": "x"},
        {"a": None, "b": "y"},
        {"a": 3, "b": None},
    ]
    # No temporary files are left behind.
    assert [p.name for p in storage.path_for(key).parent.iterdir()] == [storage.path_for(key).name]
    storage.delete(key)
    assert not storage.exists(key)
    storage.delete(key)  # deleting twice is harmless


def test_read_rows_across_row_groups(
    storage: DatasetStorage, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(storage_module, "ROW_GROUP_SIZE", 10)
    key = storage.key_for(uuid.uuid4(), uuid.uuid4())
    storage.write_frame(key, pd.DataFrame({"n": range(35)}))
    assert [r["n"] for r in storage.read_rows(key, 8, 5).to_pylist()] == [8, 9, 10, 11, 12]
    assert [r["n"] for r in storage.read_rows(key, 30, 50).to_pylist()] == [30, 31, 32, 33, 34]
    assert storage.read_rows(key, 100, 5).num_rows == 0


def test_display_filename_strips_paths_and_control_characters() -> None:
    assert display_filename("../../etc/passwd.csv") == "passwd.csv"
    assert display_filename(r"C:\Users\me\sales.csv") == "sales.csv"
    assert display_filename("bad\x00name\x07.csv") == "badname.csv"
    assert display_filename("") == "upload"
    assert display_filename(None) == "upload"
    assert len(display_filename("a" * 1000 + ".csv")) == 255

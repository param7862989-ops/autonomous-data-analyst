"""Private file storage for normalized datasets (one Parquet file per dataset).

Paths are derived only from UUIDs, never from user-supplied names, and every resolved path is
checked to be inside the storage root. Files are never served directly over HTTP.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

_KEY_PATTERN = re.compile(
    r"^datasets/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.parquet$"
)
ROW_GROUP_SIZE = 50_000


class StorageError(Exception):
    """An invalid storage key or a filesystem failure. Never shown to users verbatim."""


class DatasetStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    @staticmethod
    def key_for(user_id: uuid.UUID, dataset_id: uuid.UUID) -> str:
        return f"datasets/{user_id}/{dataset_id}.parquet"

    def path_for(self, key: str) -> Path:
        if not _KEY_PATTERN.match(key):
            raise StorageError("Invalid storage key")
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise StorageError("Storage key escapes the storage root")
        return path

    def write_frame(self, key: str, frame: pd.DataFrame) -> int:
        """Atomically write ``frame`` as Parquet; returns the file size in bytes."""
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        table = pa.Table.from_pandas(frame, preserve_index=False)
        try:
            pq.write_table(table, temporary, compression="zstd", row_group_size=ROW_GROUP_SIZE)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return path.stat().st_size

    def delete(self, key: str) -> None:
        self.path_for(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self.path_for(key).is_file()

    def read_rows(self, key: str, offset: int, limit: int) -> pa.Table:
        """Read rows [offset, offset + limit) touching only the row groups that contain them."""
        parquet = pq.ParquetFile(self.path_for(key))
        metadata = parquet.metadata
        groups: list[int] = []
        group_start = 0
        first_group_start = 0
        for index in range(metadata.num_row_groups):
            rows = metadata.row_group(index).num_rows
            group_end = group_start + rows
            if group_end > offset and group_start < offset + limit:
                if not groups:
                    first_group_start = group_start
                groups.append(index)
            group_start = group_end
        if not groups:
            return parquet.schema_arrow.empty_table()
        table = parquet.read_row_groups(groups)
        return table.slice(offset - first_group_start, limit)

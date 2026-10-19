"""Dataset use cases: create from an upload, list, read, preview, delete.

Every function that reads a dataset takes the requesting user and filters by owner, so another
user's dataset is indistinguishable from one that does not exist.
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from dataclasses import asdict
from pathlib import PurePath

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.datasets.inference import ColumnNote, infer_table
from app.datasets.ingest import IngestLimits, parse_upload
from app.datasets.profiling import build_profile
from app.datasets.storage import DatasetStorage
from app.db.models import Dataset, User
from app.errors import ConflictError, NotFoundError, ServiceUnavailableError
from app.jsonsafe import JsonScalar, rows_to_json

logger = logging.getLogger(__name__)

_INGESTION_WAIT_SECONDS = 30


def display_filename(filename: str | None) -> str:
    """The base name of an uploaded file, with control characters removed. Display only."""
    base = PurePath((filename or "").replace("\\", "/")).name
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return cleaned[:255] or "upload"


def _default_name(filename: str, sheet_name: str | None) -> str:
    stem = PurePath(filename).stem or "Dataset"
    return f"{stem} ({sheet_name})"[:255] if sheet_name else stem[:255]


def create_dataset(
    db: Session,
    *,
    user: User,
    settings: Settings,
    storage: DatasetStorage,
    ingestion_slots: threading.BoundedSemaphore,
    filename: str,
    data: bytes,
    sheet_name: str | None,
    name: str | None,
) -> Dataset:
    owned = db.scalar(select(func.count()).select_from(Dataset).where(Dataset.user_id == user.id))
    if (owned or 0) >= settings.max_datasets_per_user:
        raise ConflictError(
            f"You have reached the limit of {settings.max_datasets_per_user} datasets. Delete "
            "one to upload another.",
            code="dataset_quota_exceeded",
        )

    if not ingestion_slots.acquire(timeout=_INGESTION_WAIT_SECONDS):
        raise ServiceUnavailableError(
            "The server is busy processing other uploads. Try again in a minute.",
            code="ingestion_busy",
        )
    try:
        raw = parse_upload(filename, data, sheet_name, IngestLimits.from_settings(settings))
        typed = infer_table(raw.headers, raw.frame)
    finally:
        ingestion_slots.release()

    file_notes = [ColumnNote(code=note.code, message=note.message) for note in raw.notes]
    profile = build_profile(typed.frame, typed.columns, file_notes + typed.notes)

    dataset_id = uuid.uuid4()
    key = storage.key_for(user.id, dataset_id)
    stored_size = storage.write_frame(key, typed.frame)
    dataset = Dataset(
        id=dataset_id,
        user_id=user.id,
        name=(name or "").strip()[:255] or _default_name(filename, raw.sheet_name),
        original_filename=filename,
        file_format=raw.file_format,
        sheet_name=raw.sheet_name,
        upload_size_bytes=len(data),
        stored_size_bytes=stored_size,
        row_count=profile.row_count,
        column_count=profile.column_count,
        storage_key=key,
        columns=[asdict(column) for column in typed.columns],
        profile=profile.model_dump(mode="json"),
    )
    db.add(dataset)
    try:
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(key)
        raise
    logger.info(
        "Dataset created: rows=%d columns=%d format=%s",
        profile.row_count,
        profile.column_count,
        raw.file_format,
    )
    return dataset


def list_datasets(db: Session, *, user: User, limit: int, offset: int) -> tuple[list[Dataset], int]:
    total = db.scalar(select(func.count()).select_from(Dataset).where(Dataset.user_id == user.id))
    items = db.scalars(
        select(Dataset)
        .where(Dataset.user_id == user.id)
        .order_by(Dataset.created_at.desc(), Dataset.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return list(items), int(total or 0)


def get_dataset(db: Session, *, user: User, dataset_id: uuid.UUID) -> Dataset:
    dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id, Dataset.user_id == user.id))
    if dataset is None:
        raise NotFoundError("Dataset not found.")
    return dataset


def delete_dataset(
    db: Session, *, user: User, storage: DatasetStorage, dataset_id: uuid.UUID
) -> None:
    dataset = get_dataset(db, user=user, dataset_id=dataset_id)
    key = dataset.storage_key
    db.delete(dataset)
    db.commit()
    # The row is gone first, so a failed file delete leaves an orphaned file, never a row that
    # points to missing data.
    try:
        storage.delete(key)
    except OSError:
        logger.exception("Failed to delete dataset file; it is now orphaned")


def preview(
    storage: DatasetStorage, dataset: Dataset, *, offset: int, limit: int
) -> tuple[list[str], list[list[JsonScalar]]]:
    table = storage.read_rows(dataset.storage_key, offset, limit)
    columns = [column["name"] for column in dataset.columns]
    rows = [tuple(record.values()) for record in table.select(columns).to_pylist()]
    return columns, rows_to_json(rows)

"""Dataset upload, listing, details, preview and deletion."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile, status

from app.api.deps import CurrentUser, DbSession, RateLimiterDep, SettingsDep
from app.datasets import service
from app.datasets.profiling import DatasetProfile
from app.datasets.storage import DatasetStorage
from app.db.models import Dataset
from app.errors import PayloadTooLargeError
from app.schemas.datasets import (
    ColumnInfo,
    DatasetDetail,
    DatasetList,
    DatasetPreview,
    DatasetSummary,
    UploadLimits,
)

router = APIRouter(prefix="/datasets", tags=["datasets"])


def _storage(request: Request) -> DatasetStorage:
    storage: DatasetStorage = request.app.state.storage
    return storage


def to_detail(dataset: Dataset) -> DatasetDetail:
    summary = DatasetSummary.model_validate(dataset)
    return DatasetDetail(
        **summary.model_dump(),
        columns=[ColumnInfo.model_validate(column) for column in dataset.columns],
        profile=DatasetProfile.model_validate(dataset.profile),
    )


@router.post(
    "",
    response_model=DatasetDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a CSV or XLSX file",
    description=(
        "Validates, normalizes and profiles the file. For a workbook with several sheets, "
        "`sheet_name` is required; without it the response is 422 `sheet_required` with the "
        "sheet names in `details.sheets`."
    ),
)
def upload_dataset(
    request: Request,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
    limiter: RateLimiterDep,
    file: Annotated[UploadFile, File(description="A .csv or .xlsx file")],
    sheet_name: Annotated[str | None, Form(max_length=255)] = None,
    name: Annotated[str | None, Form(max_length=255)] = None,
) -> DatasetDetail:
    limiter.hit(
        "upload:user",
        str(user.id),
        limit=settings.uploads_per_user_per_hour,
        window_seconds=3600,
    )
    data = file.file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise PayloadTooLargeError(
            f"The file is larger than the {settings.max_upload_bytes // (1024 * 1024)} MB limit.",
            code="file_too_large",
        )
    dataset = service.create_dataset(
        db,
        user=user,
        settings=settings,
        storage=_storage(request),
        ingestion_slots=request.app.state.ingestion_slots,
        filename=service.display_filename(file.filename),
        data=data,
        sheet_name=sheet_name or None,
        name=name,
    )
    return to_detail(dataset)


@router.get("", response_model=DatasetList, summary="List your datasets")
def list_datasets(
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DatasetList:
    items, total = service.list_datasets(db, user=user, limit=limit, offset=offset)
    return DatasetList(
        items=[DatasetSummary.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/limits", response_model=UploadLimits, summary="Upload limits for this server")
def upload_limits(_: CurrentUser, settings: SettingsDep) -> UploadLimits:
    # Declared before /{dataset_id} so "limits" is not parsed as a dataset id.
    return UploadLimits(
        max_upload_bytes=settings.max_upload_bytes,
        max_rows=settings.max_dataset_rows,
        max_columns=settings.max_dataset_columns,
        accepted_extensions=[".csv", ".tsv", ".txt", ".xlsx"],
    )


@router.get("/{dataset_id}", response_model=DatasetDetail, summary="Dataset details and profile")
def get_dataset(dataset_id: uuid.UUID, user: CurrentUser, db: DbSession) -> DatasetDetail:
    return to_detail(service.get_dataset(db, user=user, dataset_id=dataset_id))


@router.get("/{dataset_id}/preview", response_model=DatasetPreview, summary="A page of rows")
def preview_dataset(
    request: Request,
    dataset_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DatasetPreview:
    dataset = service.get_dataset(db, user=user, dataset_id=dataset_id)
    columns, rows = service.preview(_storage(request), dataset, offset=offset, limit=limit)
    return DatasetPreview(
        columns=columns, rows=rows, offset=offset, limit=limit, total_rows=dataset.row_count
    )


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a dataset")
def delete_dataset(
    request: Request, dataset_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> Response:
    service.delete_dataset(db, user=user, storage=_storage(request), dataset_id=dataset_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

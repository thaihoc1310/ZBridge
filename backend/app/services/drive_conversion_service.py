import asyncio
import logging
import re
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import PurePosixPath
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.db.database import SessionLocal
from app.models import (
    DriveConversionFolder,
    DriveConversionItem,
    DriveConversionItemStatus,
    DriveConversionJob,
    DriveConversionJobStatus,
)
from app.schemas.api import (
    DriveConversionItemResponse,
    DriveConversionJobResponse,
    DriveConversionStart,
    DriveFolderResponse,
)
from app.services.google_oauth_service import google_oauth_tokens
from app.services.google_sheets_service import SheetExportError

logger = logging.getLogger("zbridge.drive_conversion")
DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
MAX_XLSX_BYTES = 25 * 1024 * 1024
MAX_SCAN_XLSX_FILES = 5000
MAX_SCAN_FOLDERS = 10000
MAX_SCAN_ENTRIES = 50000
MAX_ITEM_ATTEMPTS = 3
RETRYABLE_DRIVE_ERRORS = {"GOOGLE_API_ERROR", "GOOGLE_DRIVE_RATE_LIMIT"}
#: Exponential backoff between item attempts. Retrying a rate-limit reply with
#: no pause at all only deepens the throttle Google just applied.
DRIVE_RETRY_BASE_DELAY_SECONDS = 2.0
#: Ceiling on our *own* exponential backoff, when Google named no wait.
DRIVE_RETRY_MAX_BACKOFF_SECONDS = 60.0
#: Longest we will hold this worker asleep to honour a Retry-After. The drive
#: queue runs at concurrency 1, so a longer nap would stall every other pending
#: conversion; past this we stop retrying in-process instead of retrying early.
DRIVE_RETRY_MAX_WAIT_SECONDS = 300.0


def _parse_retry_after(value: str | None) -> float | None:
    """Read a Retry-After header, in either of the two forms Google sends."""
    if not value:
        return None
    text = value.strip()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


async def _sleep(seconds: float) -> None:
    """Indirection so a test can assert the backoff without patching asyncio."""
    await asyncio.sleep(seconds)


def _retry_delay_seconds(attempt: int, retry_after: float | None) -> float | None:
    """Seconds to wait before attempt ``attempt + 1``, or None to stop retrying.

    Never shorter than Google asked. Capping a Retry-After — as this used to,
    at 60s — means retrying before the throttle lifts, which just earns another
    rate-limit reply. When the requested wait is longer than we are willing to
    occupy the worker, the honest answer is to stop rather than retry early: the
    item lands FAILED and re-running the job picks it up, finding the Sheet
    already there if the conversion had in fact gone through.
    """
    backoff = min(
        DRIVE_RETRY_MAX_BACKOFF_SECONDS,
        DRIVE_RETRY_BASE_DELAY_SECONDS * (2**attempt),
    )
    if retry_after is None:
        return backoff
    if retry_after > DRIVE_RETRY_MAX_WAIT_SECONDS:
        return None
    return max(backoff, retry_after)


def _raise_drive_response_error(response: httpx.Response) -> None:
    reason = ""
    try:
        payload = response.json()
        details = payload.get("error", {}).get("errors", [])
        if details and isinstance(details[0], dict):
            reason = str(details[0].get("reason") or "")
    except (ValueError, AttributeError, TypeError):
        pass
    retry_after = _parse_retry_after(response.headers.get("retry-after"))
    if reason == "storageQuotaExceeded":
        raise SheetExportError(
            "GOOGLE_DRIVE_STORAGE_QUOTA",
            "Tài khoản Google đã hết dung lượng Drive nên không thể tạo file mới.",
        )
    if reason in {"rateLimitExceeded", "userRateLimitExceeded"}:
        raise SheetExportError(
            "GOOGLE_DRIVE_RATE_LIMIT",
            "Google Drive đang giới hạn tần suất thao tác.",
            retry_after=retry_after,
        )
    if response.status_code in {401, 403}:
        raise SheetExportError(
            "GOOGLE_DRIVE_ACCESS_DENIED",
            "Tài khoản Google không đủ quyền thao tác file hoặc folder này.",
        )
    if response.status_code == 404:
        raise SheetExportError(
            "GOOGLE_DRIVE_NOT_FOUND", "Không tìm thấy file hoặc folder Google Drive."
        )
    raise SheetExportError(
        "GOOGLE_API_ERROR",
        f"Google Drive API gặp lỗi HTTP {response.status_code}.",
        retry_after=retry_after,
    )


def extract_folder_id(folder_url: str) -> str:
    parsed = urlparse(folder_url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {
        "drive.google.com",
        "www.drive.google.com",
    }:
        raise AppError(
            "INVALID_DRIVE_FOLDER_URL", "Đường dẫn phải là link folder Google Drive.", 422
        )
    match = re.search(r"/folders/([A-Za-z0-9_-]+)", parsed.path)
    if not match:
        raise AppError("INVALID_DRIVE_FOLDER_URL", "Không tìm thấy mã folder Google Drive.", 422)
    return match.group(1)


async def _drive_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    token: str,
    *,
    params: dict[str, object] | None = None,
    json_body: dict[str, object] | None = None,
) -> dict[str, object]:
    response = await client.request(
        method,
        url,
        params=params,
        json=json_body,
        headers={"Authorization": f"Bearer {token}"},
    )
    if response.is_error:
        _raise_drive_response_error(response)
    try:
        return response.json()
    except ValueError as exc:
        raise SheetExportError(
            "GOOGLE_RESPONSE_INVALID", "Google Drive trả về dữ liệu không hợp lệ."
        ) from exc


async def _describe_folder(folder_id: str) -> dict[str, object]:
    token = await google_oauth_tokens.access_token()
    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
        data = await _drive_json(
            client,
            "GET",
            f"https://www.googleapis.com/drive/v3/files/{folder_id}",
            token,
            params={
                "supportsAllDrives": "true",
                "fields": (
                    "id,name,mimeType,driveId,webViewLink,capabilities("
                    "canListChildren,canAddChildren,canTrashChildren,canDeleteChildren)"
                ),
            },
        )
    if data.get("mimeType") != DRIVE_FOLDER_MIME:
        raise AppError(
            "DRIVE_LINK_NOT_FOLDER", "Đường dẫn không trỏ tới một folder Google Drive.", 422
        )
    capabilities = data.get("capabilities") or {}
    if not isinstance(capabilities, dict) or not capabilities.get("canListChildren"):
        raise AppError(
            "DRIVE_FOLDER_LIST_DENIED", "Tài khoản Google không có quyền xem nội dung folder.", 422
        )
    if not capabilities.get("canAddChildren"):
        raise AppError(
            "DRIVE_FOLDER_EDIT_DENIED",
            "Tài khoản Google chưa có quyền tạo Google Sheet trong folder.",
            422,
        )
    return data


def _folder_response(folder: DriveConversionFolder) -> DriveFolderResponse:
    return DriveFolderResponse(
        id=folder.id,
        folder_id=folder.folder_id,
        name=folder.name,
        url=folder.url,
        drive_id=folder.drive_id,
        capabilities=folder.capabilities,
        last_checked_at=folder.last_checked_at,
        created_at=folder.created_at,
    )


async def list_conversion_folders(db: AsyncSession) -> list[DriveFolderResponse]:
    folders = list(
        (await db.scalars(select(DriveConversionFolder).order_by(DriveConversionFolder.name))).all()
    )
    return [_folder_response(folder) for folder in folders]


async def save_conversion_folder(db: AsyncSession, folder_url: str) -> DriveFolderResponse:
    folder_id = extract_folder_id(folder_url)
    try:
        metadata = await _describe_folder(folder_id)
    except SheetExportError as exc:
        raise AppError(exc.code, exc.message, 422) from exc
    folder = await db.scalar(
        select(DriveConversionFolder)
        .where(DriveConversionFolder.folder_id == folder_id)
        .with_for_update()
    )
    now = datetime.now(UTC)
    canonical_url = str(
        metadata.get("webViewLink") or f"https://drive.google.com/drive/folders/{folder_id}"
    )
    if folder is None:
        folder = DriveConversionFolder(
            folder_id=folder_id,
            name=str(metadata.get("name") or "Google Drive"),
            url=canonical_url,
            drive_id=str(metadata.get("driveId") or "") or None,
            capabilities=dict(metadata.get("capabilities") or {}),
            last_checked_at=now,
        )
        db.add(folder)
    else:
        folder.name = str(metadata.get("name") or folder.name)
        folder.url = canonical_url
        folder.drive_id = str(metadata.get("driveId") or "") or None
        folder.capabilities = dict(metadata.get("capabilities") or {})
        folder.last_checked_at = now
    await db.commit()
    await db.refresh(folder)
    return _folder_response(folder)


def _item_response(item: DriveConversionItem) -> DriveConversionItemResponse:
    return DriveConversionItemResponse(
        id=item.id,
        source_file_id=item.source_file_id,
        source_name=item.source_name,
        source_url=item.source_url,
        parent_folder_id=item.parent_folder_id,
        parent_folder_name=item.parent_folder_name,
        parent_folder_url=item.parent_folder_url,
        relative_path=item.relative_path,
        size_bytes=item.size_bytes,
        can_download=item.can_download,
        can_trash=item.can_trash,
        selected=item.selected,
        status=item.status,
        destination_url=item.destination_url,
        original_trashed=item.original_trashed,
        attempt_count=item.attempt_count,
        error_code=item.error_code,
        error_message=item.error_message,
    )


def _job_response(job: DriveConversionJob) -> DriveConversionJobResponse:
    selected_items = [item for item in job.items if item.selected]
    return DriveConversionJobResponse(
        id=job.id,
        folder_id=job.folder_id,
        folder_name=job.folder.name,
        status=job.status,
        delete_originals=job.delete_originals,
        total_files=job.total_files,
        selected_files=job.selected_files,
        # Derive live progress from the item rows. The persisted counters are
        # finalized when the worker completes, but the UI polls while it runs.
        converted_files=sum(
            item.status == DriveConversionItemStatus.CONVERTED for item in selected_items
        ),
        failed_files=sum(
            item.status == DriveConversionItemStatus.FAILED for item in selected_items
        ),
        skipped_files=sum(
            item.status == DriveConversionItemStatus.SKIPPED for item in job.items
        ),
        started_at=job.started_at,
        finished_at=job.finished_at,
        error_message=job.error_message,
        created_at=job.created_at,
        items=[
            _item_response(item)
            for item in sorted(
                job.items,
                key=lambda value: (value.relative_path.casefold(), value.source_name.casefold()),
            )
        ],
    )


async def get_conversion_job(db: AsyncSession, job_id: uuid.UUID) -> DriveConversionJobResponse:
    job = await db.scalar(
        select(DriveConversionJob)
        .options(selectinload(DriveConversionJob.folder), selectinload(DriveConversionJob.items))
        .where(DriveConversionJob.id == job_id)
    )
    if job is None:
        raise AppError("DRIVE_JOB_NOT_FOUND", "Không tìm thấy lượt chuyển đổi.", 404)
    return _job_response(job)


async def create_scan_job(
    db: AsyncSession, folder_record_id: uuid.UUID
) -> DriveConversionJobResponse:
    folder = await db.get(DriveConversionFolder, folder_record_id)
    if folder is None:
        raise AppError("DRIVE_FOLDER_NOT_FOUND", "Không tìm thấy folder đã lưu.", 404)
    job = DriveConversionJob(folder_id=folder.id, status=DriveConversionJobStatus.SCANNING)
    db.add(job)
    await db.commit()
    from app.tasks.drive_conversion_tasks import scan_drive_folder_task

    try:
        scan_drive_folder_task.delay(str(job.id))
    except Exception as exc:
        logger.exception("DRIVE_SCAN_ENQUEUE_FAILED job_id=%s", job.id)
        job.status = DriveConversionJobStatus.FAILED
        job.finished_at = datetime.now(UTC)
        job.error_message = "Không đưa được tác vụ quét vào hàng đợi."
        await db.commit()
        raise AppError(
            "DRIVE_QUEUE_UNAVAILABLE",
            "Hàng đợi xử lý Drive đang không phản hồi. Hãy thử lại sau.",
            503,
        ) from exc
    return await get_conversion_job(db, job.id)


async def _list_children(
    client: httpx.AsyncClient, token: str, folder_id: str, *, remaining_entries: int
) -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    page_token: str | None = None
    while True:
        params: dict[str, object] = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "pageSize": 1000,
            "spaces": "drive",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "fields": (
                "nextPageToken,files(id,name,mimeType,size,webViewLink,capabilities("
                "canDownload,canTrash,canListChildren,canAddChildren,canTrashChildren))"
            ),
        }
        if page_token:
            params["pageToken"] = page_token
        data = await _drive_json(
            client, "GET", "https://www.googleapis.com/drive/v3/files", token, params=params
        )
        files.extend(item for item in data.get("files", []) if isinstance(item, dict))
        if len(files) > remaining_entries:
            raise AppError(
                "DRIVE_SCAN_ENTRY_LIMIT",
                f"Folder có quá {MAX_SCAN_ENTRIES} mục nên không thể quét an toàn.",
                422,
            )
        page_token = str(data.get("nextPageToken") or "") or None
        if not page_token:
            return files


async def scan_conversion_job(job_id: uuid.UUID, task_token: str) -> None:
    async with SessionLocal() as db:
        job = await db.scalar(
            select(DriveConversionJob)
            .options(selectinload(DriveConversionJob.folder))
            .where(DriveConversionJob.id == job_id)
            .with_for_update()
        )
        if job is None or job.status != DriveConversionJobStatus.SCANNING:
            return
        if job.claim_token is not None and job.claim_token != task_token:
            return
        job.claim_token = task_token
        await db.commit()
        folder = job.folder
        try:
            token = await google_oauth_tokens.access_token()
            discovered: list[DriveConversionItem] = []
            queue = deque([(folder.folder_id, folder.name, "")])
            visited: set[str] = set()
            scanned_entries = 0
            async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
                while queue:
                    if len(visited) >= MAX_SCAN_FOLDERS:
                        raise AppError(
                            "DRIVE_SCAN_FOLDER_LIMIT",
                            f"Folder có quá {MAX_SCAN_FOLDERS} folder con nên không thể "
                            "quét an toàn.",
                            422,
                        )
                    parent_id, parent_name, parent_path = queue.popleft()
                    if parent_id in visited:
                        continue
                    visited.add(parent_id)
                    entries = await _list_children(
                        client,
                        token,
                        parent_id,
                        remaining_entries=MAX_SCAN_ENTRIES - scanned_entries,
                    )
                    scanned_entries += len(entries)
                    for entry in entries:
                        entry_id = str(entry.get("id") or "")
                        name = str(entry.get("name") or "Không tên")
                        mime = str(entry.get("mimeType") or "")
                        capabilities = entry.get("capabilities") or {}
                        if mime == DRIVE_FOLDER_MIME:
                            if isinstance(capabilities, dict) and capabilities.get(
                                "canListChildren"
                            ):
                                queue.append(
                                    (entry_id, name, str(PurePosixPath(parent_path) / name))
                                )
                            continue
                        if mime != XLSX_MIME and not name.lower().endswith(".xlsx"):
                            continue
                        if len(discovered) >= MAX_SCAN_XLSX_FILES:
                            raise AppError(
                                "DRIVE_SCAN_FILE_LIMIT",
                                f"Folder có quá {MAX_SCAN_XLSX_FILES} file XLSX. "
                                "Hãy chia nhỏ folder rồi thử lại.",
                                422,
                            )
                        discovered.append(
                            DriveConversionItem(
                                job_id=job.id,
                                source_file_id=entry_id,
                                source_name=name,
                                source_url=str(
                                    entry.get("webViewLink")
                                    or f"https://drive.google.com/open?id={entry_id}"
                                ),
                                parent_folder_id=parent_id,
                                parent_folder_name=parent_name,
                                parent_folder_url=f"https://drive.google.com/drive/folders/{parent_id}",
                                relative_path=parent_path,
                                size_bytes=int(entry["size"]) if entry.get("size") else None,
                                can_download=bool(
                                    isinstance(capabilities, dict)
                                    and capabilities.get("canDownload")
                                ),
                                can_trash=bool(
                                    isinstance(capabilities, dict) and capabilities.get("canTrash")
                                ),
                            )
                        )
            await db.execute(
                delete(DriveConversionItem).where(DriveConversionItem.job_id == job.id)
            )
            # A Drive file can sit in two parents and be listed twice, which
            # violates uq_drive_conversion_job_source. Keep the first path we
            # reached it by; converting it once is what the operator wants.
            unique_discovered: dict[str, DriveConversionItem] = {}
            for candidate in discovered:
                unique_discovered.setdefault(candidate.source_file_id, candidate)
            if len(unique_discovered) != len(discovered):
                logger.info(
                    "DRIVE_SCAN_DEDUPED job_id=%s listed=%d unique=%d",
                    job_id,
                    len(discovered),
                    len(unique_discovered),
                )
            discovered = list(unique_discovered.values())
            db.add_all(discovered)
            job.total_files = len(discovered)
            job.status = DriveConversionJobStatus.READY
            job.error_message = None
            job.claim_token = None
            await db.commit()
        except Exception as exc:
            logger.exception("DRIVE_SCAN_FAILED job_id=%s", job_id)
            # The failure may well BE the commit above (a duplicate source id, an
            # over-long name), which leaves this session unusable. Discard it and
            # record the outcome on a clean one, or the handler raises
            # PendingRollbackError, hides the real error, and strands the job in
            # SCANNING with nothing to retry it.
            await db.rollback()
            await _fail_scan_job(
                job_id,
                exc.message
                if isinstance(exc, (AppError, SheetExportError))
                else "Không quét được folder Google Drive.",
            )


async def _fail_scan_job(job_id: uuid.UUID, message: str) -> None:
    async with SessionLocal() as db:
        job = await db.scalar(
            select(DriveConversionJob)
            .where(DriveConversionJob.id == job_id)
            .with_for_update()
        )
        if job is None:
            return
        job.status = DriveConversionJobStatus.FAILED
        job.error_message = message
        job.finished_at = datetime.now(UTC)
        job.claim_token = None
        await db.commit()


async def start_conversion_job(
    db: AsyncSession, job_id: uuid.UUID, data: DriveConversionStart
) -> DriveConversionJobResponse:
    job = await db.scalar(
        select(DriveConversionJob)
        .options(selectinload(DriveConversionJob.folder), selectinload(DriveConversionJob.items))
        .where(DriveConversionJob.id == job_id)
        .with_for_update()
    )
    if job is None:
        raise AppError("DRIVE_JOB_NOT_FOUND", "Không tìm thấy lượt chuyển đổi.", 404)
    if job.status not in {
        DriveConversionJobStatus.READY,
        DriveConversionJobStatus.COMPLETED,
        DriveConversionJobStatus.FAILED,
    }:
        raise AppError("DRIVE_JOB_NOT_READY", "Lượt chuyển đổi đang được xử lý.", 409)
    selected_ids = set(data.item_ids)
    selected_items = [item for item in job.items if item.id in selected_ids]
    if len(selected_items) != len(selected_ids):
        raise AppError("DRIVE_ITEM_NOT_FOUND", "Có file không thuộc lượt quét này.", 422)
    blocked = [
        item.source_name
        for item in selected_items
        if not item.can_download or (data.delete_originals and not item.can_trash)
    ]
    if blocked:
        raise AppError(
            "DRIVE_FILE_PERMISSION_DENIED",
            f"Không đủ quyền tải hoặc chuyển vào thùng rác: {', '.join(blocked[:5])}.",
            422,
        )
    oversized = [
        item.source_name
        for item in selected_items
        if item.size_bytes is not None and item.size_bytes > MAX_XLSX_BYTES
    ]
    if oversized:
        raise AppError(
            "XLSX_TOO_LARGE",
            f"File XLSX vượt giới hạn 25 MB: {', '.join(oversized[:5])}.",
            422,
        )
    for item in job.items:
        item.selected = item.id in selected_ids
        if item.selected:
            item.status = DriveConversionItemStatus.PENDING
            item.error_code = None
            item.error_message = None
        elif item.status == DriveConversionItemStatus.DISCOVERED:
            item.status = DriveConversionItemStatus.SKIPPED
    job.delete_originals = data.delete_originals
    job.selected_files = len(selected_items)
    job.status = DriveConversionJobStatus.QUEUED
    job.started_at = None
    job.finished_at = None
    job.error_message = None
    job.claim_token = None
    await db.commit()
    from app.tasks.drive_conversion_tasks import process_drive_conversion_task

    try:
        process_drive_conversion_task.delay(str(job.id))
    except Exception as exc:
        logger.exception("DRIVE_CONVERSION_ENQUEUE_FAILED job_id=%s", job.id)
        job.status = DriveConversionJobStatus.FAILED
        job.finished_at = datetime.now(UTC)
        job.error_message = "Không đưa được tác vụ chuyển đổi vào hàng đợi."
        await db.commit()
        raise AppError(
            "DRIVE_QUEUE_UNAVAILABLE",
            "Hàng đợi xử lý Drive đang không phản hồi. Hãy thử lại sau.",
            503,
        ) from exc
    return await get_conversion_job(db, job.id)


def _escape_drive_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


@dataclass(frozen=True)
class _ItemSnapshot:
    """Everything one conversion needs, so no transaction spans the Drive calls.

    Downloading 25 MB and uploading it back can take minutes; holding the row's
    transaction open for that leaves a connection idle-in-transaction for the
    whole time and blocks the API reading the same job.
    """

    id: uuid.UUID
    source_file_id: str
    source_name: str
    parent_folder_id: str
    destination_file_id: str | None
    original_trashed: bool


async def _find_existing_destination(
    client: httpx.AsyncClient, token: str, item: _ItemSnapshot
) -> dict[str, object] | None:
    source_id = _escape_drive_query(item.source_file_id)
    query = (
        f"appProperties has {{ key='zbridgeSourceId' and value='{source_id}' }} and trashed = false"
    )
    data = await _drive_json(
        client,
        "GET",
        "https://www.googleapis.com/drive/v3/files",
        token,
        params={
            "q": query,
            "pageSize": 10,
            "spaces": "drive",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
            "fields": "files(id,name,mimeType,webViewLink,parents)",
        },
    )
    for candidate in data.get("files", []):
        if (
            isinstance(candidate, dict)
            and item.parent_folder_id in (candidate.get("parents") or [])
            and candidate.get("mimeType") == SHEET_MIME
        ):
            return candidate
    return None


async def _download_xlsx(
    client: httpx.AsyncClient, token: str, source_file_id: str
) -> bytes:
    async with client.stream(
        "GET",
        f"https://www.googleapis.com/drive/v3/files/{source_file_id}",
        params={"alt": "media", "supportsAllDrives": "true"},
        headers={"Authorization": f"Bearer {token}"},
    ) as response:
        if response.is_error:
            await response.aread()
            _raise_drive_response_error(response)
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_XLSX_BYTES:
                    raise SheetExportError(
                        "XLSX_TOO_LARGE", "File XLSX vượt giới hạn 25 MB."
                    )
            except ValueError:
                pass
        content = bytearray()
        async for chunk in response.aiter_bytes():
            if len(content) + len(chunk) > MAX_XLSX_BYTES:
                raise SheetExportError(
                    "XLSX_TOO_LARGE", "File XLSX vượt giới hạn 25 MB."
                )
            content.extend(chunk)
        return bytes(content)


async def _upload_xlsx_as_sheet(
    client: httpx.AsyncClient,
    token: str,
    item: _ItemSnapshot,
    source_content: bytes,
) -> dict[str, object]:
    """Import an XLSX through a resumable session.

    Drive documents multipart uploads as suitable only up to 5 MB, while this
    tool intentionally accepts XLSX files up to 25 MB. A resumable session also
    avoids constructing a second, multipart-framed copy of the workbook in RAM.
    """
    metadata = {
        "name": re.sub(r"\.xlsx$", "", item.source_name, flags=re.IGNORECASE),
        "mimeType": SHEET_MIME,
        "parents": [item.parent_folder_id],
        "appProperties": {
            "zbridgeSourceId": item.source_file_id,
            "zbridgeItemId": str(item.id),
        },
    }
    session = await client.post(
        "https://www.googleapis.com/upload/drive/v3/files",
        params={
            "uploadType": "resumable",
            "supportsAllDrives": "true",
            "fields": "id,name,mimeType,webViewLink",
        },
        json=metadata,
        headers={
            "Authorization": f"Bearer {token}",
            "X-Upload-Content-Type": XLSX_MIME,
            "X-Upload-Content-Length": str(len(source_content)),
        },
    )
    if session.is_error:
        _raise_drive_response_error(session)
    session_url = session.headers.get("location")
    if not session_url:
        raise SheetExportError(
            "GOOGLE_RESPONSE_INVALID",
            "Google Drive không trả về phiên upload chuyển đổi.",
        )
    upload = await client.put(
        session_url,
        content=source_content,
        headers={
            "Content-Type": XLSX_MIME,
            "Content-Length": str(len(source_content)),
        },
    )
    if upload.is_error:
        _raise_drive_response_error(upload)
    try:
        payload = upload.json()
    except ValueError as exc:
        raise SheetExportError(
            "GOOGLE_RESPONSE_INVALID",
            "Google Drive trả về kết quả chuyển đổi không hợp lệ.",
        ) from exc
    if not payload.get("id"):
        raise SheetExportError(
            "GOOGLE_RESPONSE_INVALID",
            "Google Drive không trả về mã Google Sheet vừa tạo.",
        )
    return payload


async def _claim_item(item_id: uuid.UUID) -> _ItemSnapshot | None:
    """Mark the item in progress and snapshot it, in one short transaction."""
    async with SessionLocal() as db:
        item = await db.scalar(
            select(DriveConversionItem)
            .where(DriveConversionItem.id == item_id)
            .with_for_update()
        )
        if item is None or item.status == DriveConversionItemStatus.CONVERTED:
            return None
        item.status = DriveConversionItemStatus.PROCESSING
        item.attempt_count += 1
        snapshot = _ItemSnapshot(
            id=item.id,
            source_file_id=item.source_file_id,
            source_name=item.source_name,
            parent_folder_id=item.parent_folder_id,
            destination_file_id=item.destination_file_id,
            original_trashed=item.original_trashed,
        )
        await db.commit()
        return snapshot


async def _record_destination(
    item_id: uuid.UUID, destination_file_id: str, destination_url: str
) -> None:
    """Persist the Sheet before trashing the original.

    Committed separately so a crash between the two can never leave the original
    in the bin with no record of where its replacement went.
    """
    async with SessionLocal() as db:
        item = await db.get(DriveConversionItem, item_id)
        if item is None:
            return
        item.destination_file_id = destination_file_id
        item.destination_url = destination_url
        await db.commit()


async def _mark_item_converted(item_id: uuid.UUID, *, original_trashed: bool) -> None:
    async with SessionLocal() as db:
        item = await db.get(DriveConversionItem, item_id)
        if item is None:
            return
        item.original_trashed = original_trashed
        item.status = DriveConversionItemStatus.CONVERTED
        item.processed_at = datetime.now(UTC)
        item.error_code = None
        item.error_message = None
        await db.commit()


async def _convert_one(item_id: uuid.UUID, delete_original: bool) -> None:
    for attempt in range(MAX_ITEM_ATTEMPTS):
        item = await _claim_item(item_id)
        if item is None:
            return
        try:
            token = await google_oauth_tokens.access_token()
            # No session is open past this point: every write below opens its
            # own short transaction after the Drive call it records has ended.
            async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
                existing = await _find_existing_destination(client, token, item)
                if existing is None and item.destination_file_id:
                    existing = await _drive_json(
                        client,
                        "GET",
                        f"https://www.googleapis.com/drive/v3/files/{item.destination_file_id}",
                        token,
                        params={
                            "supportsAllDrives": "true",
                            "fields": "id,name,mimeType,webViewLink,parents",
                        },
                    )
                if existing is None:
                    source_content = await _download_xlsx(
                        client, token, item.source_file_id
                    )
                    existing = await _upload_xlsx_as_sheet(
                        client,
                        token,
                        item,
                        source_content,
                    )
                destination_file_id = str(existing.get("id") or "")
                destination_url = str(
                    existing.get("webViewLink")
                    or f"https://docs.google.com/spreadsheets/d/{destination_file_id}/edit"
                )
                await _record_destination(
                    item.id, destination_file_id, destination_url
                )
                original_trashed = item.original_trashed
                if delete_original and not original_trashed:
                    await _drive_json(
                        client,
                        "PATCH",
                        f"https://www.googleapis.com/drive/v3/files/{item.source_file_id}",
                        token,
                        params={"supportsAllDrives": "true", "fields": "id,trashed"},
                        json_body={"trashed": True},
                    )
                    original_trashed = True
                await _mark_item_converted(
                    item.id, original_trashed=original_trashed
                )
                return
        except Exception as exc:
            retryable = (
                isinstance(exc, SheetExportError) and exc.code in RETRYABLE_DRIVE_ERRORS
            ) or (isinstance(exc, AppError) and exc.status_code >= 500)
            if not isinstance(exc, (AppError, SheetExportError)):
                retryable = True
            retry_after = getattr(exc, "retry_after", None)
            if retryable and attempt + 1 < MAX_ITEM_ATTEMPTS:
                delay = _retry_delay_seconds(attempt, retry_after)
                if delay is not None:
                    logger.warning(
                        "DRIVE_CONVERSION_ITEM_RETRY item_id=%s attempt=%d"
                        " delay_s=%.1f code=%s",
                        item_id,
                        attempt + 1,
                        delay,
                        getattr(exc, "code", type(exc).__name__),
                    )
                    await _sleep(delay)
                    continue
                # Google asked for longer than we will hold the worker. Waiting
                # less would just be throttled again, so settle the item and let
                # a re-run pick it up.
                logger.warning(
                    "DRIVE_CONVERSION_ITEM_THROTTLED_TOO_LONG item_id=%s"
                    " retry_after_s=%.0f max_wait_s=%.0f",
                    item_id,
                    retry_after or 0.0,
                    DRIVE_RETRY_MAX_WAIT_SECONDS,
                )
            async with SessionLocal() as db:
                item = await db.get(DriveConversionItem, item_id)
                if item:
                    item.status = DriveConversionItemStatus.FAILED
                    item.processed_at = datetime.now(UTC)
                    item.error_code = (
                        exc.code
                        if isinstance(exc, (AppError, SheetExportError))
                        else "DRIVE_CONVERSION_ERROR"
                    )
                    message = (
                        exc.message
                        if isinstance(exc, (AppError, SheetExportError))
                        else "Lỗi không xác định khi chuyển file."
                    )
                    if retry_after is not None and retry_after > DRIVE_RETRY_MAX_WAIT_SECONDS:
                        # Say why we stopped, so this reads as "try again later"
                        # rather than "this file cannot be converted".
                        message = (
                            f"{message} Google yêu cầu chờ {int(retry_after)} giây;"
                            " hãy chạy lại lượt chuyển đổi sau đó."
                        )
                    item.error_message = message
                    await db.commit()
            logger.exception("DRIVE_CONVERSION_ITEM_FAILED item_id=%s", item_id)
            # Settled. Without this the loop went round again and re-tried even
            # a permission error, three times over, ignoring `retryable`.
            return


async def process_conversion_job(job_id: uuid.UUID, task_token: str) -> None:
    async with SessionLocal() as db:
        job = await db.scalar(
            select(DriveConversionJob).where(DriveConversionJob.id == job_id).with_for_update()
        )
        if job is None:
            return
        if job.status == DriveConversionJobStatus.QUEUED:
            job.claim_token = task_token
        elif (
            job.status != DriveConversionJobStatus.PROCESSING
            or job.claim_token != task_token
        ):
            return
        await db.execute(
            update(DriveConversionItem)
            .where(
                DriveConversionItem.job_id == job.id,
                DriveConversionItem.selected.is_(True),
                DriveConversionItem.status == DriveConversionItemStatus.PROCESSING,
            )
            .values(status=DriveConversionItemStatus.PENDING)
        )
        job.status = DriveConversionJobStatus.PROCESSING
        job.started_at = job.started_at or datetime.now(UTC)
        item_ids = list(
            (
                await db.scalars(
                    select(DriveConversionItem.id).where(
                        DriveConversionItem.job_id == job.id,
                        DriveConversionItem.selected.is_(True),
                        DriveConversionItem.status == DriveConversionItemStatus.PENDING,
                    )
                )
            ).all()
        )
        delete_originals = job.delete_originals
        await db.commit()
    for item_id in item_ids:
        await _convert_one(item_id, delete_originals)
    async with SessionLocal() as db:
        job = await db.scalar(
            select(DriveConversionJob).where(DriveConversionJob.id == job_id).with_for_update()
        )
        if job is None:
            return
        if (
            job.status != DriveConversionJobStatus.PROCESSING
            or job.claim_token != task_token
        ):
            return
        counts = dict(
            (
                await db.execute(
                    select(DriveConversionItem.status, func.count())
                    .where(DriveConversionItem.job_id == job.id)
                    .group_by(DriveConversionItem.status)
                )
            ).all()
        )
        selected_counts = dict(
            (
                await db.execute(
                    select(DriveConversionItem.status, func.count())
                    .where(
                        DriveConversionItem.job_id == job.id,
                        DriveConversionItem.selected.is_(True),
                    )
                    .group_by(DriveConversionItem.status)
                )
            ).all()
        )
        job.converted_files = int(
            selected_counts.get(DriveConversionItemStatus.CONVERTED, 0)
        )
        job.failed_files = int(selected_counts.get(DriveConversionItemStatus.FAILED, 0))
        job.skipped_files = int(counts.get(DriveConversionItemStatus.SKIPPED, 0))
        job.status = DriveConversionJobStatus.COMPLETED
        job.finished_at = datetime.now(UTC)
        job.claim_token = None
        await db.commit()

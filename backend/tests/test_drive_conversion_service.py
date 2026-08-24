import asyncio
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.errors import AppError
from app.db.database import Base
from app.models import (
    DriveConversionFolder,
    DriveConversionItem,
    DriveConversionItemStatus,
    DriveConversionJob,
    DriveConversionJobStatus,
)
from app.services import drive_conversion_service
from app.services.drive_conversion_service import (
    MAX_XLSX_BYTES,
    _download_xlsx,
    _upload_xlsx_as_sheet,
    create_scan_job,
    process_conversion_job,
)
from app.services.google_sheets_service import SheetExportError
from app.tasks import drive_conversion_tasks


async def _database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _folder() -> DriveConversionFolder:
    return DriveConversionFolder(
        folder_id="drive-folder",
        name="Folder test",
        url="https://drive.google.com/drive/folders/drive-folder",
        capabilities={"canListChildren": True, "canAddChildren": True},
        last_checked_at=datetime.now(UTC),
    )


async def test_different_celery_delivery_cannot_process_the_same_job(
    monkeypatch,
) -> None:
    engine, sessions = await _database()
    async with sessions() as db:
        folder = _folder()
        db.add(folder)
        await db.flush()
        job = DriveConversionJob(
            folder_id=folder.id,
            status=DriveConversionJobStatus.QUEUED,
            selected_files=1,
        )
        db.add(job)
        await db.flush()
        item = DriveConversionItem(
            job_id=job.id,
            source_file_id="xlsx-1",
            source_name="Bang cong no.xlsx",
            source_url="https://drive.google.com/open?id=xlsx-1",
            parent_folder_id=folder.folder_id,
            parent_folder_name=folder.name,
            parent_folder_url=folder.url,
            relative_path="",
            can_download=True,
            can_trash=True,
            selected=True,
            status=DriveConversionItemStatus.PENDING,
        )
        db.add(item)
        await db.commit()
        job_id = job.id

    entered = asyncio.Event()
    release = asyncio.Event()
    calls: list[str] = []

    async def convert_once(item_id, _delete_original):
        calls.append(str(item_id))
        entered.set()
        await release.wait()
        async with sessions() as db:
            stored = await db.get(DriveConversionItem, item_id)
            stored.status = DriveConversionItemStatus.CONVERTED
            await db.commit()

    monkeypatch.setattr(drive_conversion_service, "SessionLocal", sessions)
    monkeypatch.setattr(drive_conversion_service, "_convert_one", convert_once)

    owner = asyncio.create_task(process_conversion_job(job_id, "task-owner"))
    await asyncio.wait_for(entered.wait(), timeout=2)
    await process_conversion_job(job_id, "task-duplicate")
    assert len(calls) == 1
    release.set()
    await asyncio.wait_for(owner, timeout=2)

    async with sessions() as db:
        stored_job = await db.get(DriveConversionJob, job_id)
        assert stored_job.status == DriveConversionJobStatus.COMPLETED
        assert stored_job.claim_token is None
        assert stored_job.converted_files == 1
    await engine.dispose()


async def test_download_rejects_large_file_before_buffering_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-length": str(MAX_XLSX_BYTES + 1)},
            content=b"not-read",
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SheetExportError) as raised:
            await _download_xlsx(client, "token", "large-file")
    assert raised.value.code == "XLSX_TOO_LARGE"


async def test_upload_uses_resumable_session_and_preserves_conversion_metadata() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(
                200,
                headers={"location": "https://upload.example/session-1"},
                request=request,
            )
        return httpx.Response(
            200,
            json={
                "id": "sheet-1",
                "mimeType": "application/vnd.google-apps.spreadsheet",
                "webViewLink": "https://docs.google.com/spreadsheets/d/sheet-1/edit",
            },
            request=request,
        )

    item = DriveConversionItem(
        id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        source_file_id="xlsx-1",
        source_name="Bang cong no.xlsx",
        source_url="https://drive.google.com/open?id=xlsx-1",
        parent_folder_id="parent-1",
        parent_folder_name="Folder test",
        parent_folder_url="https://drive.google.com/drive/folders/parent-1",
        relative_path="",
    )
    content = b"xlsx-content"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _upload_xlsx_as_sheet(client, "token", item, content)

    assert result["id"] == "sheet-1"
    assert len(requests) == 2
    assert requests[0].url.params["uploadType"] == "resumable"
    assert requests[0].headers["x-upload-content-length"] == str(len(content))
    assert b'"zbridgeSourceId":"xlsx-1"' in requests[0].content.replace(b" ", b"")
    assert requests[1].url == "https://upload.example/session-1"
    assert requests[1].content == content


async def test_scan_enqueue_failure_is_persisted_instead_of_leaving_stuck_job(
    monkeypatch,
) -> None:
    engine, sessions = await _database()
    async with sessions() as db:
        folder = _folder()
        db.add(folder)
        await db.commit()
        folder_id = folder.id

    def fail_enqueue(_job_id: str) -> None:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(drive_conversion_tasks.scan_drive_folder_task, "delay", fail_enqueue)
    async with sessions() as db:
        with pytest.raises(AppError) as raised:
            await create_scan_job(db, folder_id)
        assert raised.value.code == "DRIVE_QUEUE_UNAVAILABLE"

    async with sessions() as db:
        job = await db.scalar(select(DriveConversionJob))
        assert job.status == DriveConversionJobStatus.FAILED
        assert job.finished_at is not None
        assert "hàng đợi" in job.error_message
    await engine.dispose()

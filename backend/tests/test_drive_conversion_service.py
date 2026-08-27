import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

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
    _ItemSnapshot,
    _parse_retry_after,
    _retry_delay_seconds,
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

    item = _ItemSnapshot(
        id=uuid.uuid4(),
        source_file_id="xlsx-1",
        source_name="Bang cong no.xlsx",
        parent_folder_id="parent-1",
        destination_file_id=None,
        original_trashed=False,
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


def test_retry_after_is_parsed_in_both_forms_google_sends() -> None:
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("") is None
    assert _parse_retry_after("nonsense") is None
    assert _parse_retry_after("30") == 30.0
    # A date already in the past yields 0 rather than a negative sleep.
    assert _parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0
    future = format_datetime(datetime.now(UTC) + timedelta(seconds=45), usegmt=True)
    parsed = _parse_retry_after(future)
    assert parsed is not None and 30 <= parsed <= 50


def test_retry_delay_grows_and_never_undercuts_google() -> None:
    # Exponential when Google says nothing, capped at our own ceiling.
    assert _retry_delay_seconds(0, None) == 2.0
    assert _retry_delay_seconds(1, None) == 4.0
    assert _retry_delay_seconds(20, None) == 60.0
    # Retry-After wins when it is longer than our own backoff...
    assert _retry_delay_seconds(0, 15.0) == 15.0
    # ...including past the 60s backoff ceiling, which must NOT clamp it: waiting
    # less than Google asked only earns another rate-limit reply.
    assert _retry_delay_seconds(0, 120.0) == 120.0
    assert _retry_delay_seconds(0, 300.0) == 300.0
    # Beyond what we will hold the worker for, do not retry early at all.
    assert _retry_delay_seconds(0, 300.1) is None
    assert _retry_delay_seconds(0, 900.0) is None
    # A shorter Retry-After does not shrink the backoff below our floor.
    assert _retry_delay_seconds(2, 1.0) == 8.0


async def _fake_token() -> str:
    return "token"


async def _seed_one_item(sessions) -> uuid.UUID:
    async with sessions() as db:
        folder = _folder()
        db.add(folder)
        await db.flush()
        job = DriveConversionJob(
            folder_id=folder.id,
            status=DriveConversionJobStatus.PROCESSING,
            delete_originals=False,
        )
        db.add(job)
        await db.flush()
        item = DriveConversionItem(
            job_id=job.id,
            source_file_id="xlsx-retry",
            source_name="Bang.xlsx",
            source_url="https://drive.google.com/open?id=xlsx-retry",
            parent_folder_id="parent-1",
            parent_folder_name="Folder test",
            parent_folder_url="https://drive.google.com/drive/folders/parent-1",
            relative_path="",
            selected=True,
            can_download=True,
            status=DriveConversionItemStatus.PENDING,
        )
        db.add(item)
        await db.commit()
        return item.id


async def test_a_rate_limited_item_waits_before_retrying(monkeypatch) -> None:
    """Retrying a throttle reply with no pause only deepens the throttle."""
    engine, sessions = await _database()
    item_id = await _seed_one_item(sessions)

    slept: list[float] = []

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    async def rate_limited(*_args, **_kwargs):
        raise SheetExportError(
            "GOOGLE_DRIVE_RATE_LIMIT", "Bị giới hạn tần suất.", retry_after=12.0
        )

    monkeypatch.setattr(drive_conversion_service, "SessionLocal", sessions)
    monkeypatch.setattr(drive_conversion_service, "_sleep", record_sleep)
    monkeypatch.setattr(
        drive_conversion_service.google_oauth_tokens, "access_token", _fake_token
    )
    monkeypatch.setattr(
        drive_conversion_service, "_find_existing_destination", rate_limited
    )

    await drive_conversion_service._convert_one(item_id, False)

    # One sleep per retry, not per attempt: the final failure does not wait.
    assert len(slept) == drive_conversion_service.MAX_ITEM_ATTEMPTS - 1
    # Retry-After of 12s beats the 2s/4s exponential floor.
    assert slept == [12.0, 12.0]
    async with sessions() as db:
        item = await db.get(DriveConversionItem, item_id)
        assert item is not None
        assert item.status == DriveConversionItemStatus.FAILED
        assert item.error_code == "GOOGLE_DRIVE_RATE_LIMIT"
        assert item.attempt_count == drive_conversion_service.MAX_ITEM_ATTEMPTS
    await engine.dispose()


async def test_a_permission_error_is_not_retried(monkeypatch) -> None:
    """`retryable` was decided and then ignored: the loop fell through and went again."""
    engine, sessions = await _database()
    item_id = await _seed_one_item(sessions)

    calls = 0

    async def denied(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise SheetExportError("GOOGLE_DRIVE_ACCESS_DENIED", "Không đủ quyền.")

    slept: list[float] = []

    monkeypatch.setattr(drive_conversion_service, "SessionLocal", sessions)
    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(drive_conversion_service, "_sleep", record_sleep)
    monkeypatch.setattr(
        drive_conversion_service.google_oauth_tokens, "access_token", _fake_token
    )
    monkeypatch.setattr(drive_conversion_service, "_find_existing_destination", denied)

    await drive_conversion_service._convert_one(item_id, False)

    assert calls == 1, "loi khong the thu lai van bi goi lai"
    assert slept == []
    async with sessions() as db:
        item = await db.get(DriveConversionItem, item_id)
        assert item is not None
        assert item.status == DriveConversionItemStatus.FAILED
        assert item.attempt_count == 1
    await engine.dispose()


async def test_the_claim_is_committed_before_any_drive_call(monkeypatch) -> None:
    """No DB transaction may span the download/upload.

    The session used to stay open across a 25 MB download and a resumable
    upload, holding a connection idle-in-transaction for minutes.
    """
    engine, sessions = await _database()
    item_id = await _seed_one_item(sessions)
    observed: list[str] = []

    async def observe_then_fail(*_args, **_kwargs):
        # A separate session sees the claim, so the claiming transaction closed.
        async with sessions() as probe:
            item = await probe.get(DriveConversionItem, item_id)
            assert item is not None
            observed.append(item.status.value)
        raise SheetExportError("GOOGLE_DRIVE_ACCESS_DENIED", "dừng ở đây")

    monkeypatch.setattr(drive_conversion_service, "SessionLocal", sessions)
    monkeypatch.setattr(
        drive_conversion_service.google_oauth_tokens, "access_token", _fake_token
    )
    monkeypatch.setattr(
        drive_conversion_service, "_find_existing_destination", observe_then_fail
    )

    await drive_conversion_service._convert_one(item_id, False)

    assert observed == [DriveConversionItemStatus.PROCESSING.value]
    await engine.dispose()


async def test_a_long_throttle_stops_instead_of_retrying_early(monkeypatch) -> None:
    """Google asking for 5+ minutes must not become a 60-second retry.

    The delay used to be clamped to 60s, so a long throttle was retried while
    still throttled — burning both remaining attempts for nothing.
    """
    engine, sessions = await _database()
    item_id = await _seed_one_item(sessions)

    calls = 0
    slept: list[float] = []

    async def throttled(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise SheetExportError(
            "GOOGLE_DRIVE_RATE_LIMIT", "Bị giới hạn tần suất.", retry_after=900.0
        )

    async def record_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(drive_conversion_service, "SessionLocal", sessions)
    monkeypatch.setattr(drive_conversion_service, "_sleep", record_sleep)
    monkeypatch.setattr(
        drive_conversion_service.google_oauth_tokens, "access_token", _fake_token
    )
    monkeypatch.setattr(drive_conversion_service, "_find_existing_destination", throttled)

    await drive_conversion_service._convert_one(item_id, False)

    assert calls == 1, "khong duoc thu lai som hon Google yeu cau"
    assert slept == []
    async with sessions() as db:
        item = await db.get(DriveConversionItem, item_id)
        assert item is not None
        assert item.status == DriveConversionItemStatus.FAILED
        assert item.error_code == "GOOGLE_DRIVE_RATE_LIMIT"
        # The operator is told this is a wait, not a broken file.
        assert "900" in (item.error_message or "")
        assert "chạy lại" in (item.error_message or "")
    await engine.dispose()

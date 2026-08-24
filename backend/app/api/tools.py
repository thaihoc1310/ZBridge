import uuid
from typing import Literal
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db, require_permission
from app.core.config import settings
from app.core.errors import AppError
from app.core.permissions import (
    DEBT_REMINDER_BULK_APPLY,
    DEBT_REMINDER_HISTORY_READ,
    DRIVE_CONVERSION_MANAGE,
    MENTION_FOLLOWUP_CANCEL,
    MENTION_FOLLOWUP_READ,
)
from app.models import Role, User
from app.models.entities import DebtReminderStatus
from app.schemas.api import (
    ActiveMentionCompanyListResponse,
    ActiveMentionTaskResponse,
    DebtReminderBulkApply,
    DebtReminderBulkApplyResponse,
    DebtReminderBulkPreviewResponse,
    DebtReminderBulkSchedule,
    DebtReminderRunListResponse,
    DriveConversionJobResponse,
    DriveConversionStart,
    DriveFolderCreate,
    DriveFolderResponse,
    GoogleOAuthStartResponse,
    GoogleOAuthStatusResponse,
)
from app.services.drive_conversion_service import (
    create_scan_job,
    get_conversion_job,
    list_conversion_folders,
    save_conversion_folder,
    start_conversion_job,
)
from app.services.google_oauth_service import (
    build_authorization_url,
    decode_oauth_state,
    disconnect_google,
    exchange_authorization_code,
    google_connection_status,
)
from app.services.tools_service import (
    apply_bulk_debt_reminders,
    cancel_mention_followup,
    list_active_mention_followups,
    list_debt_reminder_runs,
    preview_bulk_debt_reminders,
)

router = APIRouter(prefix="/tools", tags=["tools"])


def _google_callback_redirect(**params: str) -> RedirectResponse:
    public_url = next(iter(settings.cors_origins), "http://localhost:5173")
    query = urlencode({"panel": "drive", **params})
    return RedirectResponse(f"{public_url.rstrip('/')}/tools?{query}", status_code=303)


@router.get("/mention-followups", response_model=ActiveMentionCompanyListResponse)
async def active_mention_followups(
    search: str | None = None,
    sort: Literal["name", "count", "next_due", "newest"] = "next_due",
    direction: Literal["asc", "desc"] = "asc",
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(MENTION_FOLLOWUP_READ)),
) -> ActiveMentionCompanyListResponse:
    return await list_active_mention_followups(
        db, search=search, sort=sort, direction=direction, page=page, limit=limit
    )


@router.post(
    "/mention-followups/{followup_id}/cancel",
    response_model=ActiveMentionTaskResponse,
)
async def stop_mention_followup(
    followup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(MENTION_FOLLOWUP_CANCEL)),
) -> ActiveMentionTaskResponse:
    return await cancel_mention_followup(db, followup_id)


@router.post("/debt-reminders/bulk/preview", response_model=DebtReminderBulkPreviewResponse)
async def debt_bulk_preview(
    data: DebtReminderBulkSchedule,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(DEBT_REMINDER_BULK_APPLY)),
) -> DebtReminderBulkPreviewResponse:
    return await preview_bulk_debt_reminders(db, data)


@router.post("/debt-reminders/bulk/apply", response_model=DebtReminderBulkApplyResponse)
async def debt_bulk_apply(
    data: DebtReminderBulkApply,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(DEBT_REMINDER_BULK_APPLY)),
) -> DebtReminderBulkApplyResponse:
    return await apply_bulk_debt_reminders(db, data)


@router.get("/debt-reminders/history", response_model=DebtReminderRunListResponse)
async def debt_history(
    month: str | None = None,
    run_status: DebtReminderStatus | None = Query(default=None, alias="status"),
    search: str | None = None,
    sort: Literal["scheduled", "company", "status"] = "scheduled",
    direction: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(DEBT_REMINDER_HISTORY_READ)),
) -> DebtReminderRunListResponse:
    return await list_debt_reminder_runs(
        db,
        month=month,
        status=run_status,
        search=search,
        sort=sort,
        direction=direction,
        page=page,
        limit=limit,
    )


@router.get("/drive/folders", response_model=list[DriveFolderResponse])
async def drive_folders(
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(DRIVE_CONVERSION_MANAGE)),
) -> list[DriveFolderResponse]:
    return await list_conversion_folders(db)


@router.get("/google/oauth/status", response_model=GoogleOAuthStatusResponse)
async def google_oauth_status(
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(DRIVE_CONVERSION_MANAGE)),
) -> GoogleOAuthStatusResponse:
    return GoogleOAuthStatusResponse.model_validate(await google_connection_status(db))


@router.post("/google/oauth/start", response_model=GoogleOAuthStartResponse)
async def google_oauth_start(
    actor: User = Depends(require_permission(DRIVE_CONVERSION_MANAGE)),
) -> GoogleOAuthStartResponse:
    return GoogleOAuthStartResponse(authorization_url=build_authorization_url(actor.id))


@router.get("/google/oauth/callback", include_in_schema=False)
async def google_oauth_callback(
    state: str,
    code: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    try:
        actor_id = decode_oauth_state(state)
        if error or not code:
            raise AppError(
                "GOOGLE_OAUTH_CANCELLED", "Google chưa cấp quyền cho ZBridge.", 400
            )
        actor = await db.scalar(
            select(User)
            .options(selectinload(User.role).selectinload(Role.permissions))
            .where(User.id == actor_id, User.is_active.is_(True))
        )
        if actor is None or DRIVE_CONVERSION_MANAGE not in actor.permission_codes:
            raise AppError(
                "GOOGLE_OAUTH_FORBIDDEN",
                "Tài khoản khởi tạo kết nối không còn quyền quản lý Drive.",
                403,
            )
        connection = await exchange_authorization_code(
            db, code=code, connected_by_user_id=actor.id
        )
        return _google_callback_redirect(google="connected", email=connection.email)
    except AppError as exc:
        return _google_callback_redirect(google="error", message=exc.message)
    except httpx.HTTPError:
        return _google_callback_redirect(
            google="error",
            message="Không kết nối được tới Google. Hãy thử lại sau.",
        )


@router.delete("/google/oauth", status_code=status.HTTP_204_NO_CONTENT)
async def google_oauth_disconnect(
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(DRIVE_CONVERSION_MANAGE)),
) -> None:
    await disconnect_google(db)


@router.post("/drive/folders", response_model=DriveFolderResponse)
async def add_drive_folder(
    data: DriveFolderCreate,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(DRIVE_CONVERSION_MANAGE)),
) -> DriveFolderResponse:
    return await save_conversion_folder(db, data.url)


@router.post(
    "/drive/folders/{folder_id}/scan",
    response_model=DriveConversionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def scan_drive_folder(
    folder_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(DRIVE_CONVERSION_MANAGE)),
) -> DriveConversionJobResponse:
    return await create_scan_job(db, folder_id)


@router.get("/drive/jobs/{job_id}", response_model=DriveConversionJobResponse)
async def drive_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(DRIVE_CONVERSION_MANAGE)),
) -> DriveConversionJobResponse:
    return await get_conversion_job(db, job_id)


@router.post(
    "/drive/jobs/{job_id}/start",
    response_model=DriveConversionJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_drive_job(
    job_id: uuid.UUID,
    data: DriveConversionStart,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(DRIVE_CONVERSION_MANAGE)),
) -> DriveConversionJobResponse:
    return await start_conversion_job(db, job_id, data)

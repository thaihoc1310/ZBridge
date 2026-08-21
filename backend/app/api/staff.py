from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_any_permission, require_permission
from app.core.permissions import MENTION_BULK_APPLY, STAFF_MANAGE
from app.db.database import get_db
from app.models import User
from app.schemas.api import (
    BulkMentionApplyResult,
    BulkMentionPreview,
    BulkMentionUpdate,
    GroupMemberResponse,
    StaffMemberResponse,
    StaffRosterUpdate,
)
from app.services.staff_service import (
    apply_bulk_mention,
    list_staff,
    list_staff_candidates,
    preview_bulk_mention,
    save_staff,
)

router = APIRouter(prefix="/staff", tags=["staff"])


@router.get("", response_model=list[StaffMemberResponse])
async def index(
    db: AsyncSession = Depends(get_db),
    # The bulk editor picks from this list, so it may read it too.
    _actor: User = Depends(require_any_permission(STAFF_MANAGE, MENTION_BULK_APPLY)),
) -> list[StaffMemberResponse]:
    return await list_staff(db)


@router.get("/candidates", response_model=list[GroupMemberResponse])
async def candidates(
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(STAFF_MANAGE)),
) -> list[GroupMemberResponse]:
    return await list_staff_candidates(db)


@router.put("", response_model=list[StaffMemberResponse])
async def replace(
    data: StaffRosterUpdate,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(STAFF_MANAGE)),
) -> list[StaffMemberResponse]:
    return await save_staff(db, data)


@router.post("/bulk-mention/preview", response_model=BulkMentionPreview)
async def preview(
    data: BulkMentionUpdate,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(MENTION_BULK_APPLY)),
) -> BulkMentionPreview:
    return await preview_bulk_mention(db, data)


@router.post("/bulk-mention/apply", response_model=BulkMentionApplyResult)
async def apply(
    data: BulkMentionUpdate,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(MENTION_BULK_APPLY)),
) -> BulkMentionApplyResult:
    return await apply_bulk_mention(db, data)

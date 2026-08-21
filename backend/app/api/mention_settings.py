from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.permissions import MENTION_POLICY_MANAGE
from app.db.database import get_db
from app.models import User
from app.schemas.api import MentionClassifierSettingsResponse, MentionClassifierSettingsUpdate
from app.services.mention_settings_service import get_mention_settings, save_mention_settings

router = APIRouter(prefix="/mention-settings", tags=["mention-settings"])


@router.get("", response_model=MentionClassifierSettingsResponse)
async def detail(
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(MENTION_POLICY_MANAGE)),
) -> MentionClassifierSettingsResponse:
    return await get_mention_settings(db)


@router.put("", response_model=MentionClassifierSettingsResponse)
async def update(
    data: MentionClassifierSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(MENTION_POLICY_MANAGE)),
) -> MentionClassifierSettingsResponse:
    return await save_mention_settings(db, data)

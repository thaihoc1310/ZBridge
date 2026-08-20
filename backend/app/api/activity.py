from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.permissions import ACTIVITY_READ
from app.db.database import get_db
from app.models import User
from app.models.entities import DeliveryStatus
from app.schemas.api import DeliveryLogListResponse
from app.services.delivery_service import list_delivery_logs

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("", response_model=DeliveryLogListResponse)
async def activity(
    search: str | None = Query(default=None, max_length=255),
    status: DeliveryStatus | None = None,
    today: bool = False,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(ACTIVITY_READ)),
) -> DeliveryLogListResponse:
    return await list_delivery_logs(db, search, status, today, page, limit)

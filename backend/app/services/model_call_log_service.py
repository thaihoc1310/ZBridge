import math

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ModelCallLog
from app.models.entities import ModelCallStatus
from app.schemas.api import ModelCallLogListResponse, ModelCallLogResponse


async def list_model_call_logs(
    db: AsyncSession,
    *,
    search: str | None,
    status: ModelCallStatus | None,
    page: int,
    limit: int,
) -> ModelCallLogListResponse:
    filters = []
    if search:
        needle = f"%{search.strip()}%"
        filters.append(
            or_(
                ModelCallLog.customer_name.ilike(needle),
                ModelCallLog.model.ilike(needle),
                ModelCallLog.error_type.ilike(needle),
                ModelCallLog.error_message.ilike(needle),
            )
        )
    if status:
        filters.append(ModelCallLog.status == status)

    total = int(
        await db.scalar(select(func.count()).select_from(ModelCallLog).where(*filters))
        or 0
    )
    rows = list(
        (
            await db.scalars(
                select(ModelCallLog)
                .where(*filters)
                .order_by(ModelCallLog.created_at.desc())
                .offset((page - 1) * limit)
                .limit(limit)
            )
        ).all()
    )
    return ModelCallLogListResponse(
        items=[
            ModelCallLogResponse(
                id=row.id,
                customer_id=row.customer_id,
                customer_name=row.customer_name,
                trigger=row.trigger,
                provider=row.provider,
                model=row.model,
                request_payload=row.request_payload,
                response_payload=row.response_payload,
                status=row.status,
                outcome=row.outcome,
                error_type=row.error_type,
                error_message=row.error_message,
                input_tokens=row.input_tokens,
                output_tokens=row.output_tokens,
                latency_ms=row.latency_ms,
                created_at=row.created_at,
                finished_at=row.finished_at,
            )
            for row in rows
        ],
        total=total,
        page=page,
        limit=limit,
        pages=max(1, math.ceil(total / limit)),
    )

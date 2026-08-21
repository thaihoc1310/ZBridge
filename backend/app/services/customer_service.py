import math
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError
from app.models import Customer, ZaloGroup
from app.schemas.api import CustomerListResponse, CustomerResponse, CustomerUpdate


def customer_response(customer: Customer) -> CustomerResponse:
    group = customer.group
    return CustomerResponse(
        id=customer.id,
        name=group.name,
        avatar_url=group.avatar_url,
        has_debt=customer.has_debt,
        last_debt_paid_at=customer.last_debt_paid_at,
        note=customer.note,
        folder_url=customer.folder_url,
        zalo_group_id=group.zalo_group_id,
        member_count=group.member_count,
        is_available=group.is_available,
        last_synced_at=group.last_synced_at,
        created_at=group.created_at,
        updated_at=customer.updated_at,
    )


async def list_customers(
    db: AsyncSession,
    search: str | None,
    debt: str | None,
    availability: str,
    page: int,
    limit: int,
) -> CustomerListResponse:
    filters = []
    if search:
        needle = f"%{search.strip()}%"
        filters.append(
            or_(
                ZaloGroup.name.ilike(needle),
                Customer.note.ilike(needle),
            )
        )
    if debt == "owed":
        filters.append(Customer.has_debt.is_(True))
    elif debt == "clear":
        filters.append(Customer.has_debt.is_(False))
    if availability == "available":
        filters.append(ZaloGroup.is_available.is_(True))
    elif availability == "unavailable":
        filters.append(ZaloGroup.is_available.is_(False))

    base = select(Customer).join(Customer.group).where(*filters)
    total = int(
        await db.scalar(
            select(func.count()).select_from(Customer).join(Customer.group).where(*filters)
        )
        or 0
    )
    items = list(
        (
            await db.scalars(
                base.options(selectinload(Customer.group))
                .order_by(Customer.has_debt.desc(), ZaloGroup.name.asc())
                .offset((page - 1) * limit)
                .limit(limit)
            )
        ).all()
    )
    return CustomerListResponse(
        items=[customer_response(item) for item in items],
        total=total,
        page=page,
        limit=limit,
        pages=max(1, math.ceil(total / limit)),
    )


async def get_customer(db: AsyncSession, customer_id: uuid.UUID) -> Customer:
    customer = await db.scalar(
        select(Customer)
        .options(selectinload(Customer.group))
        .execution_options(populate_existing=True)
        .where(Customer.id == customer_id)
    )
    if customer is None:
        raise AppError("CUSTOMER_NOT_FOUND", "Không tìm thấy khách hàng.", 404)
    return customer


async def update_customer(
    db: AsyncSession, customer_id: uuid.UUID, data: CustomerUpdate
) -> CustomerResponse:
    customer = await get_customer(db, customer_id)
    fields = data.model_fields_set

    if "has_debt" in fields and data.has_debt is not None and data.has_debt != customer.has_debt:
        if customer.has_debt and not data.has_debt:
            customer.last_debt_paid_at = datetime.now(UTC)
        customer.has_debt = data.has_debt

    if "note" in fields:
        customer.note = data.note.strip() if data.note and data.note.strip() else None

    if "folder_url" in fields:
        customer.folder_url = data.folder_url

    await db.commit()
    return customer_response(await get_customer(db, customer_id))


async def ensure_customers_for_groups(db: AsyncSession) -> None:
    group_ids = set((await db.scalars(select(ZaloGroup.id))).all())
    customer_group_ids = set((await db.scalars(select(Customer.zalo_group_id))).all())
    for group_id in group_ids - customer_group_ids:
        db.add(Customer(id=group_id, zalo_group_id=group_id))

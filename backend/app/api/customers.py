import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.database import get_db
from app.schemas.api import (
    CustomerListResponse,
    CustomerResponse,
    CustomerUpdate,
    DebtReminderResponse,
    DebtReminderUpdate,
    DeliveryLogResponse,
    GroupMemberResponse,
    MentionAutomationResponse,
    MentionAutomationUpdate,
    MessageCreate,
    SyncResponse,
)
from app.services.customer_service import (
    customer_response,
    get_customer,
    list_customers,
    update_customer,
)
from app.services.debt_reminder_service import get_debt_reminder, save_debt_reminder
from app.services.delivery_service import send_customer_message
from app.services.group_service import sync_groups
from app.services.mention_automation_service import (
    get_mention_automation,
    list_group_members,
    save_mention_automation,
)

router = APIRouter(
    prefix="/customers", tags=["customers"], dependencies=[Depends(get_current_user)]
)


@router.get("", response_model=CustomerListResponse)
async def customers(
    search: str | None = Query(default=None, max_length=255),
    debt: str | None = Query(default=None, pattern="^(owed|clear)$"),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> CustomerListResponse:
    return await list_customers(db, search, debt, page, limit)


@router.post("/sync", response_model=SyncResponse)
async def sync(db: AsyncSession = Depends(get_db)) -> SyncResponse:
    return await sync_groups(db)


@router.get("/{customer_id}", response_model=CustomerResponse)
async def detail(customer_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> CustomerResponse:
    return customer_response(await get_customer(db, customer_id))


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update(
    customer_id: uuid.UUID,
    data: CustomerUpdate,
    db: AsyncSession = Depends(get_db),
) -> CustomerResponse:
    return await update_customer(db, customer_id, data)


@router.get("/{customer_id}/members", response_model=list[GroupMemberResponse])
async def members(
    customer_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[GroupMemberResponse]:
    customer = await get_customer(db, customer_id)
    return await list_group_members(db, customer.zalo_group_id)


@router.get("/{customer_id}/mention-automation", response_model=MentionAutomationResponse)
async def mention_automation(
    customer_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> MentionAutomationResponse:
    customer = await get_customer(db, customer_id)
    return await get_mention_automation(db, customer.zalo_group_id)


@router.put("/{customer_id}/mention-automation", response_model=MentionAutomationResponse)
async def update_mention_automation(
    customer_id: uuid.UUID,
    data: MentionAutomationUpdate,
    db: AsyncSession = Depends(get_db),
) -> MentionAutomationResponse:
    customer = await get_customer(db, customer_id)
    return await save_mention_automation(db, customer.zalo_group_id, data)


@router.post("/{customer_id}/messages", response_model=DeliveryLogResponse)
async def create_message(
    customer_id: uuid.UUID,
    data: MessageCreate,
    db: AsyncSession = Depends(get_db),
) -> DeliveryLogResponse:
    return await send_customer_message(db, customer_id, data)


@router.get("/{customer_id}/debt-reminder", response_model=DebtReminderResponse)
async def debt_reminder(
    customer_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> DebtReminderResponse:
    return await get_debt_reminder(db, customer_id)


@router.put("/{customer_id}/debt-reminder", response_model=DebtReminderResponse)
async def update_debt_reminder(
    customer_id: uuid.UUID,
    data: DebtReminderUpdate,
    db: AsyncSession = Depends(get_db),
) -> DebtReminderResponse:
    return await save_debt_reminder(db, customer_id, data)

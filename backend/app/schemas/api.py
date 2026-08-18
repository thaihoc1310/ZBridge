import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.entities import BotStatus, DebtReminderStatus, DeliveryStatus, DeliveryType


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str


class BotStatusResponse(BaseModel):
    status: BotStatus
    account_name: str | None = None
    zalo_user_id: str | None = None
    avatar_url: str | None = None
    group_count: int = 0
    session_active: bool = False
    last_connected_at: datetime | None = None
    last_health_check_at: datetime | None = None
    last_error: str | None = None


class QRResponse(BaseModel):
    status: str
    qr: str | None = None
    account_name: str | None = None


class CustomerResponse(BaseModel):
    id: uuid.UUID
    name: str
    avatar_url: str | None
    has_debt: bool
    last_debt_paid_at: datetime | None
    note: str | None
    folder_url: str | None
    zalo_group_id: str
    member_count: int
    is_available: bool
    last_synced_at: datetime
    created_at: datetime
    updated_at: datetime


class CustomerListResponse(BaseModel):
    items: list[CustomerResponse]
    total: int
    page: int
    limit: int
    pages: int


class CustomerUpdate(BaseModel):
    has_debt: bool | None = None
    note: str | None = Field(default=None, max_length=10000)
    folder_url: str | None = Field(default=None, max_length=2000)

    @field_validator("folder_url")
    @classmethod
    def validate_folder_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Đường dẫn thư mục phải bắt đầu bằng http:// hoặc https://.")
        return value


class SyncResponse(BaseModel):
    inserted: int
    updated: int
    unavailable: int
    total: int
    synced_at: datetime


class MessageCreate(BaseModel):
    type: Literal["TEXT"] = "TEXT"
    content: str = Field(min_length=1, max_length=5000)


class DeliveryLogResponse(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    customer_name: str
    type: DeliveryType
    status: DeliveryStatus
    zalo_message_id: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime


class DeliveryLogListResponse(BaseModel):
    items: list[DeliveryLogResponse]
    total: int
    page: int
    limit: int
    pages: int


class DashboardResponse(BaseModel):
    bot_status: BotStatus
    customer_count: int
    customers_with_debt: int
    messages_today: int
    failed_today: int
    last_sync_at: datetime | None
    last_successful_message_at: datetime | None


class HealthResponse(BaseModel):
    api: str
    database: str
    zalo_gateway: str
    zalo: str


class GroupMemberResponse(BaseModel):
    user_id: str
    display_name: str
    avatar_url: str | None = None


class MentionTargetInput(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=255)
    avatar_url: str | None = None


class MentionTimeWindow(BaseModel):
    start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def validate_order(self):
        if self.start >= self.end:
            raise ValueError("Giờ bắt đầu phải sớm hơn giờ kết thúc.")
        return self


class MentionAutomationUpdate(BaseModel):
    enabled: bool = True
    delay_minutes: int = Field(default=120, ge=1, le=10080)
    active_windows: list[MentionTimeWindow] = Field(
        default_factory=lambda: [
            MentionTimeWindow(start="08:00", end="12:00"),
            MentionTimeWindow(start="14:00", end="18:00"),
        ],
        min_length=1,
        max_length=24,
    )
    targets: list[MentionTargetInput] = Field(min_length=1, max_length=100)


class MentionTargetResponse(BaseModel):
    user_id: str
    display_name: str
    avatar_url: str | None = None


class MentionAutomationResponse(BaseModel):
    id: uuid.UUID | None = None
    group_id: uuid.UUID
    enabled: bool
    delay_minutes: int
    active_windows: list[MentionTimeWindow]
    targets: list[MentionTargetResponse]
    pending_followups: int = 0
    updated_at: datetime | None = None


class DebtReminderTextPart(BaseModel):
    type: Literal["text"]
    text: str = Field(min_length=1, max_length=5000)


class DebtReminderMentionPart(BaseModel):
    type: Literal["mention"]
    user_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=255)


DebtReminderMessagePart = DebtReminderTextPart | DebtReminderMentionPart


class DebtReminderUpdate(BaseModel):
    enabled: bool = True
    day_of_month: int = Field(default=25, ge=1, le=31)
    repeat_interval_days: int = Field(default=3, ge=1, le=31)
    send_time: str = Field(default="09:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    message_parts: list[DebtReminderMessagePart] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_message(self):
        content = "".join(
            part.text if isinstance(part, DebtReminderTextPart) else f"@{part.display_name}"
            for part in self.message_parts
        )
        if not content.strip():
            raise ValueError("Nội dung nhắc công nợ không được để trống.")
        if len(content) > 5000:
            raise ValueError("Nội dung nhắc công nợ không được vượt quá 5000 ký tự.")
        return self


class DebtReminderResponse(BaseModel):
    id: uuid.UUID | None = None
    customer_id: uuid.UUID
    enabled: bool
    day_of_month: int
    repeat_interval_days: int
    send_time: str
    message_parts: list[DebtReminderMessagePart]
    next_run_at: datetime | None = None
    last_run_status: DebtReminderStatus | None = None
    last_run_at: datetime | None = None
    last_error: str | None = None
    updated_at: datetime | None = None


class IncomingMention(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    position: int = Field(ge=0)
    length: int = Field(ge=1)


class IncomingGroupMessage(BaseModel):
    group_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    sender_id: str | None = Field(default=None, max_length=128)
    content: str = Field(default="", max_length=10000)
    mentions: list[IncomingMention] = Field(default_factory=list, max_length=100)


class IncomingEventResponse(BaseModel):
    scheduled: bool
    followup_id: uuid.UUID | None = None
    matched_targets: int = 0

import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.entities import BotStatus, DebtReminderStatus, DeliveryStatus, DeliveryType


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class PermissionResponse(BaseModel):
    code: str
    name: str
    category: str


class RoleResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None = None
    is_system: bool
    permissions: list[str]
    user_count: int = 0


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    full_name: str | None = None
    is_active: bool
    role: RoleResponse
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role_id: uuid.UUID
    is_active: bool = True


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role_id: uuid.UUID | None = None
    is_active: bool | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_change(self):
        if self.current_password == self.new_password:
            raise ValueError("Mật khẩu mới phải khác mật khẩu hiện tại.")
        return self


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    permissions: list[str] = Field(min_length=1, max_length=100)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    permissions: list[str] | None = Field(default=None, max_length=100)


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
    listener_status: str | None = None
    events_healthy: bool = False


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
    debt_file_url: str | None
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
    debt_file_url: str | None = Field(default=None, max_length=2000)

    @field_validator("debt_file_url")
    @classmethod
    def validate_debt_file_url(cls, value: str | None) -> str | None:
        """Shape only. Whether Google can actually read it is checked on save."""
        if value is None or not value.strip():
            return None
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Đường dẫn phải bắt đầu bằng http:// hoặc https://.")
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
    # Two independent features share the delay and the active windows below.
    mention_tag_enabled: bool = True
    price_inquiry_enabled: bool = False
    delay_minutes: int = Field(default=120, ge=1, le=10080)
    active_windows: list[MentionTimeWindow] = Field(
        default_factory=lambda: [
            MentionTimeWindow(start="08:00", end="12:00"),
            MentionTimeWindow(start="14:00", end="18:00"),
        ],
        min_length=1,
        max_length=24,
    )
    # Both lists may be empty and both features may be off: a customer that does
    # not use tagging yet, or one switched on before anybody was picked, is a
    # normal state rather than an error.
    targets: list[MentionTargetInput] = Field(default_factory=list, max_length=100)
    price_targets: list[MentionTargetInput] = Field(default_factory=list, max_length=100)


class MentionTargetResponse(BaseModel):
    user_id: str
    display_name: str
    avatar_url: str | None = None


class MentionAutomationResponse(BaseModel):
    id: uuid.UUID | None = None
    group_id: uuid.UUID
    enabled: bool
    mention_tag_enabled: bool = True
    price_inquiry_enabled: bool = False
    delay_minutes: int
    active_windows: list[MentionTimeWindow]
    targets: list[MentionTargetResponse]
    price_targets: list[MentionTargetResponse] = Field(default_factory=list)
    pending_followups: int = 0
    updated_at: datetime | None = None


class StaffMemberInput(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=255)
    avatar_url: str | None = None
    note: str | None = Field(default=None, max_length=255)


class StaffMemberResponse(StaffMemberInput):
    mention_customer_count: int = 0
    price_customer_count: int = 0


class StaffRosterUpdate(BaseModel):
    members: list[StaffMemberInput] = Field(default_factory=list, max_length=200)


class BulkMentionUpdate(MentionAutomationUpdate):
    """The same shape the per-customer form posts, plus who to apply it to."""

    customer_ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)


class BulkMentionPreviewRow(BaseModel):
    customer_id: uuid.UUID
    name: str
    is_available: bool
    has_automation: bool
    current_target_count: int
    #: Reminders this customer would lose, counted only where the configuration
    #: actually changes — an identical rewrite cancels nothing.
    active_followups: int
    will_change: bool = True
    #: People who would be written here but are not in the Zalo group.
    missing_members: list[str] = Field(default_factory=list)


class BulkMentionPreview(BaseModel):
    rows: list[BulkMentionPreviewRow]
    #: Set when membership could not be read, so the warnings above are unknown
    #: rather than empty.
    gateway_error: str | None = None


class BulkMentionApplyResult(BaseModel):
    updated: int
    created: int
    #: Already had exactly this configuration, so their running reminders were
    #: left alone rather than cancelled and restarted.
    unchanged: int = 0
    skipped: list[str] = Field(default_factory=list)
    cancelled_followups: int = 0
    dropped_members: dict[str, int] = Field(default_factory=dict)


class MentionClassifierSettingsUpdate(BaseModel):
    ai_classifier_enabled: bool = True
    bare_mention_requires_response: bool = True
    skip_phrases: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_skip_phrases(self):
        if any(not phrase.strip() or len(phrase) > 100 for phrase in self.skip_phrases):
            raise ValueError("Mỗi câu bỏ qua phải có từ 1 đến 100 ký tự.")
        return self


class MentionClassifierSettingsResponse(MentionClassifierSettingsUpdate):
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
    text: str | None = Field(default=None, max_length=255)


class IncomingGroupMessage(BaseModel):
    group_id: str = Field(min_length=1, max_length=128)
    message_id: str = Field(min_length=1, max_length=128)
    sender_id: str | None = Field(default=None, max_length=128)
    sender_display_name: str | None = Field(default=None, max_length=255)
    sent_at: datetime | None = None
    content: str = Field(default="", max_length=10000)
    # Generous on purpose: rejecting an event would also drop the reply
    # acknowledgement it carries, leaving the follow-up loop running forever.
    mentions: list[IncomingMention] = Field(default_factory=list, max_length=1000)


class GatewayAlert(BaseModel):
    """An operator alert raised by the Zalo gateway (which cannot reach Celery)."""

    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2000)
    severity: Literal["WARNING", "ERROR", "CRITICAL"] = "ERROR"
    context: dict[str, str] = Field(default_factory=dict, max_length=12)


class IncomingEventResponse(BaseModel):
    scheduled: bool
    followup_id: uuid.UUID | None = None
    matched_targets: int = 0

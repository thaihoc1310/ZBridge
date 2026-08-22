from __future__ import annotations

import enum
import uuid
from datetime import datetime, time

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.types import Uuid

from app.db.database import Base


class BotStatus(enum.StrEnum):
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    ERROR = "ERROR"


class DeliveryStatus(enum.StrEnum):
    SENT = "SENT"
    FAILED = "FAILED"


class DeliveryType(enum.StrEnum):
    MANUAL_MESSAGE = "MANUAL_MESSAGE"
    MENTION_AUTOMATION = "MENTION_AUTOMATION"
    DEBT_REMINDER_IMAGE = "DEBT_REMINDER_IMAGE"
    DEBT_REMINDER_LINK = "DEBT_REMINDER_LINK"
    DEBT_REMINDER_MESSAGE = "DEBT_REMINDER_MESSAGE"


class DebtReminderStatus(enum.StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class MentionTargetKind(enum.StrEnum):
    """Which automation a target is listed for; one person may be in both."""

    MENTION = "MENTION"
    PRICE = "PRICE"


class MentionFollowupTrigger(enum.StrEnum):
    """What created the follow-up, and therefore how a failed classification ends.

    MENTION fails open — a human already tagged somebody, so tagging again costs
    one message. PRICE_INQUIRY fails closed — nobody tagged anyone and only the
    classifier separates "báo giá cho anh" from "đánh giá nhân viên", so a
    failure here must stay silent rather than spam the customer's group.
    """

    MENTION = "MENTION"
    PRICE_INQUIRY = "PRICE_INQUIRY"


class MentionFollowupStatus(enum.StrEnum):
    CLASSIFYING = "CLASSIFYING"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SENT = "SENT"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Permission(TimestampMixin, Base):
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)

    roles: Mapped[list[Role]] = relationship(
        secondary="role_permissions", back_populates="permissions"
    )


class Role(TimestampMixin, Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    permissions: Mapped[list[Permission]] = relationship(
        secondary="role_permissions",
        back_populates="roles",
        order_by="Permission.code",
    )
    users: Mapped[list[User]] = relationship(back_populates="role")


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    role: Mapped[Role] = relationship(back_populates="users")

    @property
    def permission_codes(self) -> frozenset[str]:
        """Requires ``role.permissions`` to be eager-loaded (see ``api.deps``)."""
        return frozenset(permission.code for permission in self.role.permissions)


class ZaloAccount(TimestampMixin, Base):
    __tablename__ = "zalo_accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    zalo_user_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[BotStatus] = mapped_column(
        Enum(BotStatus, native_enum=False), default=BotStatus.AUTH_REQUIRED, nullable=False
    )
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    groups: Mapped[list[ZaloGroup]] = relationship(back_populates="account")


class ZaloGroup(TimestampMixin, Base):
    __tablename__ = "zalo_groups"
    __table_args__ = (
        UniqueConstraint("zalo_account_id", "zalo_group_id", name="uq_account_zalo_group"),
        Index("ix_zalo_groups_available_name", "is_available", "name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    zalo_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("zalo_accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    zalo_group_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    member_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    missing_sync_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    last_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    account: Mapped[ZaloAccount] = relationship(back_populates="groups")
    customer: Mapped[Customer | None] = relationship(
        back_populates="group", cascade="all, delete-orphan", uselist=False
    )
    mention_automation: Mapped[MentionAutomation | None] = relationship(
        back_populates="group", cascade="all, delete-orphan", uselist=False
    )


class Customer(TimestampMixin, Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    zalo_group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("zalo_groups.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    has_debt: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    last_debt_paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    #: The Google Sheet the debt reminder screenshots, verified when saved.
    debt_file_url: Mapped[str | None] = mapped_column(Text)

    group: Mapped[ZaloGroup] = relationship(back_populates="customer")
    delivery_logs: Mapped[list[BotDeliveryLog]] = relationship(back_populates="customer")
    debt_reminder: Mapped[DebtReminderAutomation | None] = relationship(
        back_populates="customer", cascade="all, delete-orphan", uselist=False
    )


class BotDeliveryLog(Base):
    __tablename__ = "bot_delivery_logs"
    __table_args__ = (
        Index("ix_bot_delivery_logs_customer_created", "customer_id", "created_at"),
        Index("ix_bot_delivery_logs_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    type: Mapped[DeliveryType] = mapped_column(
        Enum(DeliveryType, native_enum=False), nullable=False
    )
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, native_enum=False), nullable=False
    )
    zalo_message_id: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    customer: Mapped[Customer] = relationship(back_populates="delivery_logs")


class MentionAutomation(TimestampMixin, Base):
    __tablename__ = "mention_automations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    zalo_group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("zalo_groups.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    #: Master switch, kept in step with the two feature flags below so the
    #: scheduler and classifier can keep asking one question.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mention_tag_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    price_inquiry_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    delay_minutes: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    active_windows: Mapped[list[dict[str, str]]] = mapped_column(
        JSON,
        default=lambda: [
            {"start": "08:00", "end": "12:00"},
            {"start": "14:00", "end": "18:00"},
        ],
        nullable=False,
    )

    group: Mapped[ZaloGroup] = relationship(back_populates="mention_automation")
    targets: Mapped[list[MentionTarget]] = relationship(
        back_populates="automation",
        cascade="all, delete-orphan",
        order_by="MentionTarget.display_name",
    )
    followups: Mapped[list[MentionFollowup]] = relationship(
        back_populates="automation", cascade="all, delete-orphan"
    )
    context_messages: Mapped[list[MentionContextMessage]] = relationship(
        back_populates="automation", cascade="all, delete-orphan"
    )


class MentionClassifierSettings(TimestampMixin, Base):
    """One global policy shared by every mention automation."""

    __tablename__ = "mention_classifier_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    ai_classifier_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    bare_mention_requires_response: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
    skip_phrases: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class MentionContextMessage(Base):
    """Short-lived inbound message history used only by the mention classifier."""

    __tablename__ = "mention_context_messages"
    __table_args__ = (
        UniqueConstraint("automation_id", "message_id", name="uq_mention_context_message"),
        Index("ix_mention_context_group_sent", "automation_id", "sent_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    automation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("mention_automations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sender_id: Mapped[str | None] = mapped_column(String(128))
    sender_display_name: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    mentions: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list, nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    automation: Mapped[MentionAutomation] = relationship(back_populates="context_messages")


class MentionTarget(TimestampMixin, Base):
    __tablename__ = "mention_targets"
    __table_args__ = (
        UniqueConstraint(
            "automation_id", "zalo_user_id", "kind", name="uq_mention_target_user"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    automation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("mention_automations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    zalo_user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    kind: Mapped[MentionTargetKind] = mapped_column(
        Enum(MentionTargetKind, native_enum=False),
        default=MentionTargetKind.MENTION,
        server_default=MentionTargetKind.MENTION.value,
        nullable=False,
    )

    automation: Mapped[MentionAutomation] = relationship(back_populates="targets")


class StaffMember(TimestampMixin, Base):
    """The handful of people who get tagged, kept once instead of per customer.

    Picking a target used to mean fetching one group's members from Zalo. A
    company-wide roster makes the bulk editor instant, and makes "this person is
    in 6 of 8 customers" answerable without asking the gateway again.
    """

    __tablename__ = "staff_members"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    zalo_user_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(String(255))


class MentionFollowup(Base):
    __tablename__ = "mention_followups"
    __table_args__ = (
        UniqueConstraint("automation_id", "source_message_id", name="uq_mention_followup_source"),
        Index("ix_mention_followups_due", "status", "due_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    automation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("mention_automations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_sender_id: Mapped[str | None] = mapped_column(String(128))
    trigger: Mapped[MentionFollowupTrigger] = mapped_column(
        Enum(MentionFollowupTrigger, native_enum=False),
        default=MentionFollowupTrigger.MENTION,
        server_default=MentionFollowupTrigger.MENTION.value,
        nullable=False,
    )
    target_user_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    target_display_names: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[MentionFollowupStatus] = mapped_column(
        Enum(MentionFollowupStatus, native_enum=False),
        default=MentionFollowupStatus.PENDING,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_message_id: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    classification_model: Mapped[str | None] = mapped_column(String(128))
    classification_result: Mapped[list[dict[str, object]] | None] = mapped_column(JSON)
    classification_error: Mapped[str | None] = mapped_column(Text)
    classification_input_tokens: Mapped[int | None] = mapped_column(Integer)
    classification_output_tokens: Mapped[int | None] = mapped_column(Integer)
    classification_latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    automation: Mapped[MentionAutomation] = relationship(back_populates="followups")


class DebtReminderAutomation(TimestampMixin, Base):
    __tablename__ = "debt_reminder_automations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    day_of_month: Mapped[int] = mapped_column(Integer, default=25, nullable=False)
    repeat_interval_days: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    send_time: Mapped[time] = mapped_column(
        Time(timezone=False), default=time(9, 0), nullable=False
    )
    message_parts: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    customer: Mapped[Customer] = relationship(back_populates="debt_reminder")
    runs: Mapped[list[DebtReminderRun]] = relationship(
        back_populates="automation", cascade="all, delete-orphan"
    )


class DebtReminderRun(TimestampMixin, Base):
    __tablename__ = "debt_reminder_runs"
    __table_args__ = (
        UniqueConstraint(
            "automation_id", "scheduled_for", name="uq_debt_reminder_run_schedule"
        ),
        Index("ix_debt_reminder_runs_due", "status", "retry_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    automation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("debt_reminder_automations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[DebtReminderStatus] = mapped_column(
        Enum(DebtReminderStatus, native_enum=False),
        default=DebtReminderStatus.PENDING,
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sheet_file_id: Mapped[str | None] = mapped_column(String(255))
    sheet_name: Mapped[str | None] = mapped_column(String(255))
    sheet_url: Mapped[str | None] = mapped_column(Text)
    image_message_id: Mapped[str | None] = mapped_column(String(128))
    link_message_id: Mapped[str | None] = mapped_column(String(128))
    text_message_id: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)

    automation: Mapped[DebtReminderAutomation] = relationship(back_populates="runs")

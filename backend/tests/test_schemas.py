import pytest
from pydantic import ValidationError

from app.schemas.api import (
    LoginRequest,
    MentionAutomationUpdate,
    MentionTargetInput,
    MessageCreate,
)


def test_message_content_limits() -> None:
    assert MessageCreate(content="Xin chào").content == "Xin chào"
    with pytest.raises(ValidationError):
        MessageCreate(content="")
    with pytest.raises(ValidationError):
        MessageCreate(content="x" * 5001)


def test_login_requires_valid_email_and_password_length() -> None:
    request = LoginRequest(email="admin@example.com", password="12345678")
    assert request.email == "admin@example.com"
    with pytest.raises(ValidationError):
        LoginRequest(email="not-an-email", password="12345678")


def test_mention_automation_accepts_an_empty_setup_but_not_a_bad_delay() -> None:
    target = MentionTargetInput(user_id="zalo-user-1", display_name="Nguyễn Minh Anh")
    data = MentionAutomationUpdate(targets=[target])
    assert data.delay_minutes == 120
    assert [window.model_dump() for window in data.active_windows] == [
        {"start": "08:00", "end": "12:00"},
        {"start": "14:00", "end": "18:00"},
    ]

    # A customer that does not use tagging yet, or one switched on before anybody
    # was picked, is a normal state to save rather than an error.
    empty = MentionAutomationUpdate(
        mention_tag_enabled=False, price_inquiry_enabled=False, targets=[]
    )
    assert empty.targets == [] and empty.price_targets == []
    assert MentionAutomationUpdate(targets=[]).targets == []

    with pytest.raises(ValidationError):
        MentionAutomationUpdate(delay_minutes=0, targets=[target])
    with pytest.raises(ValidationError):
        MentionAutomationUpdate(active_windows=[], targets=[target])

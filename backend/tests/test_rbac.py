import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.errors import AppError
from app.core.permissions import (
    ACTIVITY_READ,
    ADMIN_ROLE_CODE,
    ALL_PERMISSION_CODES,
    CUSTOMER_READ,
    MENTION_BULK_APPLY,
    MENTION_POLICY_MANAGE,
    MENTION_READ,
    MENTION_UPDATE,
    MODEL_ACTIVITY_READ,
    PERMISSION_CATALOG,
    STAFF_MANAGE,
    SYSTEM_ROLES,
    USER_MANAGEMENT_PERMISSIONS,
    USER_READ,
    USER_UPDATE,
)
from app.core.security import hash_password
from app.db.database import Base, get_db
from app.main import app
from app.models import Permission, Role, User
from app.services.rbac_service import sync_rbac
from app.services.user_service import delete_user, get_user

ADMIN_EMAIL = "admin@zbridge.vn"
ADMIN_PASSWORD = "admin-password"
OWNER_EMAIL = "owner@zbridge.vn"
OWNER_PASSWORD = "owner-password"
OWNER_ROLE_CODE = "BUSINESS_OWNER"

# Endpoints that must stay reachable without a session.
PUBLIC_ROUTES = {("POST", "/api/auth/login"), ("POST", "/api/auth/logout"), ("GET", "/health")}


def test_permission_catalog_is_consistent() -> None:
    codes = [definition.code for definition in PERMISSION_CATALOG]
    assert len(codes) == len(set(codes)), "permission codes must be unique"
    for role in SYSTEM_ROLES:
        assert role.permissions <= ALL_PERMISSION_CODES

    by_code = {role.code: role for role in SYSTEM_ROLES}
    # ADMIN is the only reserved role: everything else is the operator's to
    # shape, so nothing but ADMIN may be locked against editing.
    assert set(by_code) == {ADMIN_ROLE_CODE}
    assert by_code[ADMIN_ROLE_CODE].permissions == ALL_PERMISSION_CODES


@pytest.fixture
async def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as db:
        await sync_rbac(db)
        admin_role = await db.scalar(select(Role).where(Role.code == ADMIN_ROLE_CODE))
        assert admin_role is not None
        # Not bootstrapped any more: an operator role is something the admin
        # builds, so build one the way the API would.
        owner_role = Role(
            code=OWNER_ROLE_CODE,
            name="Chủ doanh nghiệp",
            description="Toàn quyền vận hành, không quản lý người dùng.",
            is_system=False,
        )
        owner_role.permissions = list(
            (
                await db.scalars(
                    select(Permission).where(
                        Permission.code.in_(
                            sorted(ALL_PERMISSION_CODES - USER_MANAGEMENT_PERMISSIONS)
                        )
                    )
                )
            ).all()
        )
        db.add(owner_role)
        await db.flush()
        db.add_all(
            [
                User(
                    email=ADMIN_EMAIL,
                    full_name="Quản trị hệ thống",
                    password_hash=hash_password(ADMIN_PASSWORD),
                    role_id=admin_role.id,
                ),
                User(
                    email=OWNER_EMAIL,
                    full_name="Chủ doanh nghiệp",
                    password_hash=hash_password(OWNER_PASSWORD),
                    role_id=owner_role.id,
                ),
            ]
        )
        await db.commit()

    yield factory
    await engine.dispose()


@pytest.fixture
async def client(session_factory):
    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://zbridge.test"
    ) as http:
        yield http
    app.dependency_overrides.clear()


async def _login(client: AsyncClient, email: str, password: str) -> dict:
    response = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_login_rate_limit_rejects_before_password_verification(
    client, monkeypatch
) -> None:
    async def reject_attempt(_ip: str, _email: str) -> bool:
        return False

    monkeypatch.setattr("app.api.auth.login_attempt_allowed", reject_attempt)
    response = await client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "LOGIN_RATE_LIMITED"


async def test_mention_classifier_settings_are_global_for_owner_and_admin(client) -> None:
    await _login(client, OWNER_EMAIL, OWNER_PASSWORD)
    updated = await client.put(
        "/api/mention-settings",
        json={
            "ai_classifier_enabled": True,
            "bare_mention_requires_response": True,
            "skip_phrases": ["ok", "cảm ơn"],
        },
    )
    assert updated.status_code == 200, updated.text

    client.cookies.clear()
    await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    fetched = await client.get("/api/mention-settings")
    assert fetched.status_code == 200
    assert fetched.json()["skip_phrases"] == ["ok", "cảm ơn"]


async def test_every_api_route_requires_a_session(client) -> None:
    """A new endpoint that forgets its permission dependency fails here."""
    checked = 0
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            route = (method.upper(), path)
            if route in PUBLIC_ROUTES:
                continue
            concrete = path
            while "{" in concrete:
                start = concrete.index("{")
                end = concrete.index("}", start)
                concrete = concrete[:start] + str(uuid.uuid4()) + concrete[end + 1 :]
            response = await client.request(method.upper(), concrete, json={})
            assert response.status_code == 401, f"{route} returned {response.status_code}"
            assert response.json()["error"]["code"] == "UNAUTHORIZED"
            checked += 1
    assert checked >= 25


async def test_business_owner_runs_operations_but_cannot_manage_users(client) -> None:
    session = await _login(client, OWNER_EMAIL, OWNER_PASSWORD)
    permissions = set(session["role"]["permissions"])

    assert session["role"]["code"] == OWNER_ROLE_CODE
    assert session["role"]["is_system"] is False
    assert {"customer:read", "customer:update", "message:send", "debt_reminder:update"} <= (
        permissions
    )
    assert not permissions & USER_MANAGEMENT_PERMISSIONS

    assert (await client.get("/api/customers")).status_code == 200
    assert (await client.get("/api/dashboard")).status_code == 200
    assert (await client.get("/api/activity")).status_code == 200
    assert (await client.get("/api/activity/model-calls")).status_code == 200

    for path in ("/api/users", "/api/roles"):
        forbidden = await client.get(path)
        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "FORBIDDEN"


async def test_delivery_and_model_activity_permissions_are_independent(
    client, session_factory
) -> None:
    async def grant_only(code: str) -> None:
        async with session_factory() as db:
            role = await db.scalar(
                select(Role)
                .options(selectinload(Role.permissions))
                .where(Role.code == OWNER_ROLE_CODE)
            )
            permission = await db.scalar(select(Permission).where(Permission.code == code))
            assert role is not None and permission is not None
            role.permissions = [permission]
            await db.commit()

    await grant_only(ACTIVITY_READ)
    await _login(client, OWNER_EMAIL, OWNER_PASSWORD)
    assert (await client.get("/api/activity")).status_code == 200
    assert (await client.get("/api/activity/model-calls")).status_code == 403

    client.cookies.clear()
    await grant_only(MODEL_ACTIVITY_READ)
    await _login(client, OWNER_EMAIL, OWNER_PASSWORD)
    assert (await client.get("/api/activity")).status_code == 403
    assert (await client.get("/api/activity/model-calls")).status_code == 200


async def test_admin_creates_a_user_who_can_then_sign_in(client) -> None:
    await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    roles = await client.get("/api/roles")
    assert roles.status_code == 200
    owner_role_id = next(
        role["id"] for role in roles.json() if role["code"] == OWNER_ROLE_CODE
    )

    created = await client.post(
        "/api/users",
        json={
            "email": "Staff@ZBridge.vn",
            "full_name": "Nhân viên vận hành",
            "password": "staff-password",
            "role_id": owner_role_id,
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["email"] == "staff@zbridge.vn"
    assert created.json()["role"]["code"] == OWNER_ROLE_CODE

    duplicate = await client.post(
        "/api/users",
        json={
            "email": "staff@zbridge.vn",
            "password": "another-password",
            "role_id": owner_role_id,
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "EMAIL_ALREADY_USED"

    assert len((await client.get("/api/users")).json()) == 3

    client.cookies.clear()
    staff_session = await _login(client, "staff@zbridge.vn", "staff-password")
    assert staff_session["full_name"] == "Nhân viên vận hành"
    assert (await client.get("/api/users")).status_code == 403


async def test_admin_cannot_lock_itself_out(client) -> None:
    session = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    roles = (await client.get("/api/roles")).json()
    owner_role_id = next(
        role["id"] for role in roles if role["code"] == OWNER_ROLE_CODE
    )

    demote_self = await client.patch(
        f"/api/users/{session['id']}", json={"role_id": owner_role_id}
    )
    assert demote_self.status_code == 422
    assert demote_self.json()["error"]["code"] == "CANNOT_MODIFY_SELF"

    disable_self = await client.patch(
        f"/api/users/{session['id']}", json={"is_active": False}
    )
    assert disable_self.status_code == 422
    assert disable_self.json()["error"]["code"] == "CANNOT_MODIFY_SELF"

    delete_self = await client.delete(f"/api/users/{session['id']}")
    assert delete_self.status_code == 422
    assert delete_self.json()["error"]["code"] == "CANNOT_MODIFY_SELF"


async def test_deactivated_user_loses_access(client) -> None:
    admin = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    owner = next(
        user
        for user in (await client.get("/api/users")).json()
        if user["email"] == OWNER_EMAIL
    )
    assert admin["id"] != owner["id"]

    disabled = await client.patch(f"/api/users/{owner['id']}", json={"is_active": False})
    assert disabled.status_code == 200
    assert disabled.json()["is_active"] is False

    client.cookies.clear()
    denied = await client.post(
        "/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "ACCOUNT_DISABLED"


async def test_password_change_keeps_this_session_and_kills_older_tokens(client) -> None:
    session = await _login(client, OWNER_EMAIL, OWNER_PASSWORD)
    issued_earlier = datetime.now(UTC) - timedelta(minutes=5)
    stale_token = jwt.encode(
        {
            "sub": session["id"],
            "iat": issued_earlier,
            "exp": issued_earlier + timedelta(hours=8),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    assert (
        await client.get(
            "/api/auth/me", headers={"Authorization": f"Bearer {stale_token}"}
        )
    ).status_code == 200

    wrong_current = await client.post(
        "/api/auth/change-password",
        json={"current_password": "not-the-password", "new_password": "brand-new-password"},
    )
    assert wrong_current.status_code == 400
    assert wrong_current.json()["error"]["code"] == "INVALID_CREDENTIALS"

    same_password = await client.post(
        "/api/auth/change-password",
        json={"current_password": OWNER_PASSWORD, "new_password": OWNER_PASSWORD},
    )
    assert same_password.status_code == 422

    changed = await client.post(
        "/api/auth/change-password",
        json={"current_password": OWNER_PASSWORD, "new_password": "brand-new-password"},
    )
    assert changed.status_code == 200, changed.text

    # The session that performed the change was handed a refreshed cookie.
    assert (await client.get("/api/auth/me")).status_code == 200

    client.cookies.clear()
    stale = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {stale_token}"}
    )
    assert stale.status_code == 401
    assert stale.json()["error"]["code"] == "PASSWORD_CHANGED"

    assert (
        await client.post(
            "/api/auth/login", json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD}
        )
    ).status_code == 401
    await _login(client, OWNER_EMAIL, "brand-new-password")


async def test_customer_tagging_rights_do_not_reach_the_global_policy(
    client, session_factory
) -> None:
    """One customer's tagging config and the system-wide policy are separate grants.

    They shared `mention:update` before, so anyone trusted to set up tagging for
    a single group could also switch the classifier off for every group.
    """
    async with session_factory() as db:
        role = Role(code="TAG_OPERATOR", name="Vận hành tag", is_system=False)
        role.permissions = list(
            (
                await db.scalars(
                    select(Permission).where(
                        Permission.code.in_(
                        [CUSTOMER_READ, MENTION_READ, MENTION_UPDATE]
                    )
                    )
                )
            ).all()
        )
        db.add(role)
        await db.flush()
        db.add(
            User(
                email="tagger@zbridge.vn",
                password_hash=hash_password("tagger-password"),
                role_id=role.id,
            )
        )
        await db.commit()

    session = await _login(client, "tagger@zbridge.vn", "tagger-password")
    # The nav hides a tab whose permission is missing, so the whole page has to
    # be behind one code — a readable page with a dead Save button would just
    # be a tab this role can see but never use.
    assert MENTION_POLICY_MANAGE not in session["role"]["permissions"]
    assert (await client.get("/api/mention-settings")).status_code == 403

    blocked = await client.put(
        "/api/mention-settings",
        json={
            "ai_classifier_enabled": False,
            "bare_mention_requires_response": True,
            "skip_phrases": [],
        },
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "FORBIDDEN"

    # Per-customer tagging config is a separate grant and still works.
    assert (await client.get("/api/customers")).status_code == 200

    # The admin, who holds the new code, still gets through.
    client.cookies.clear()
    await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    allowed = await client.put(
        "/api/mention-settings",
        json={
            "ai_classifier_enabled": False,
            "bare_mention_requires_response": True,
            "skip_phrases": ["ok"],
        },
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["ai_classifier_enabled"] is False


async def test_each_tag_feature_is_its_own_grant(client, session_factory) -> None:
    """Editing one customer must not carry the roster or the bulk overwrite.

    A single bulk apply rewrites every customer at once, so it cannot ride along
    with the permission somebody gets to configure one group.
    """
    async with session_factory() as db:
        role = Role(code="TAG_ONE_CUSTOMER", name="Chỉ sửa từng khách", is_system=False)
        role.permissions = list(
            (
                await db.scalars(
                    select(Permission).where(
                        Permission.code.in_([CUSTOMER_READ, MENTION_READ, MENTION_UPDATE])
                    )
                )
            ).all()
        )
        db.add(role)
        await db.flush()
        db.add(
            User(
                email="one@zbridge.vn",
                password_hash=hash_password("one-password"),
                role_id=role.id,
            )
        )
        await db.commit()

    session = await _login(client, "one@zbridge.vn", "one-password")
    held = set(session["role"]["permissions"])
    assert not held & {STAFF_MANAGE, MENTION_BULK_APPLY, MENTION_POLICY_MANAGE}

    for method, path in (
        ("GET", "/api/staff"),
        ("PUT", "/api/staff"),
        ("GET", "/api/staff/candidates"),
        ("POST", "/api/staff/bulk-mention/preview"),
        ("POST", "/api/staff/bulk-mention/apply"),
        ("PUT", "/api/mention-settings"),
    ):
        response = await client.request(method, path, json={})
        assert response.status_code == 403, f"{method} {path} -> {response.status_code}"

    # The admin holds all three and gets through.
    client.cookies.clear()
    await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert (await client.get("/api/staff")).status_code == 200


async def test_admin_is_the_only_locked_role(client) -> None:
    """Every seeded role except ADMIN must be editable in the UI.

    The frontend gates its edit and delete buttons on `is_system`, so anything
    left reserved here silently becomes unmanageable for the operator.
    """
    await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    roles = (await client.get("/api/roles")).json()
    assert [role["code"] for role in roles if role["is_system"]] == [ADMIN_ROLE_CODE]

    owner = next(role for role in roles if role["code"] == OWNER_ROLE_CODE)
    trimmed = await client.patch(
        f"/api/roles/{owner['id']}", json={"permissions": ["customer:read"]}
    )
    assert trimmed.status_code == 200, trimmed.text
    assert trimmed.json()["permissions"] == ["customer:read"]


async def test_a_role_dropped_from_the_catalog_is_demoted_not_deleted(
    session_factory,
) -> None:
    """Retiring a system role must not strand the accounts assigned to it."""
    async with session_factory() as db:
        reserved = Role(code="RETIRED_ROLE", name="Sắp nghỉ hưu", is_system=True)
        reserved.permissions = list(
            (await db.scalars(select(Permission).where(Permission.code == USER_READ))).all()
        )
        db.add(reserved)
        await db.commit()
        role_id = reserved.id

    # RETIRED_ROLE is not in SYSTEM_ROLES, so the next boot should hand it over.
    async with session_factory() as db:
        await sync_rbac(db)

    async with session_factory() as db:
        role = await db.scalar(
            select(Role).options(selectinload(Role.permissions)).where(Role.id == role_id)
        )
        assert role is not None, "a retired role must survive the sync"
        assert role.is_system is False
        assert [permission.code for permission in role.permissions] == [USER_READ]

        admin = await db.scalar(select(Role).where(Role.code == ADMIN_ROLE_CODE))
        assert admin is not None and admin.is_system is True


async def test_custom_roles_are_editable_and_system_roles_are_not(client) -> None:
    await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    roles = (await client.get("/api/roles")).json()
    system_role_id = next(role["id"] for role in roles if role["is_system"])

    blocked = await client.patch(
        f"/api/roles/{system_role_id}", json={"permissions": ["customer:read"]}
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "SYSTEM_ROLE_READ_ONLY"
    assert (await client.delete(f"/api/roles/{system_role_id}")).status_code == 422

    catalog = await client.get("/api/roles/permissions")
    assert catalog.status_code == 200
    assert len(catalog.json()) == len(PERMISSION_CATALOG)

    created = await client.post(
        "/api/roles",
        json={
            "name": "Kế toán công nợ",
            "description": "Chỉ theo dõi công nợ.",
            "permissions": ["dashboard:read", "customer:read", "debt_reminder:read"],
        },
    )
    assert created.status_code == 201, created.text
    role = created.json()
    assert role["code"] == "KE_TOAN_CONG_NO"
    assert role["is_system"] is False
    assert set(role["permissions"]) == {
        "dashboard:read",
        "customer:read",
        "debt_reminder:read",
    }

    rejected = await client.post(
        "/api/roles", json={"name": "Sai quyền", "permissions": ["customer:teleport"]}
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "UNKNOWN_PERMISSION"

    accountant = await client.post(
        "/api/users",
        json={
            "email": "ketoan@zbridge.vn",
            "password": "ketoan-password",
            "role_id": role["id"],
        },
    )
    assert accountant.status_code == 201

    in_use = await client.delete(f"/api/roles/{role['id']}")
    assert in_use.status_code == 422
    assert in_use.json()["error"]["code"] == "ROLE_IN_USE"

    client.cookies.clear()
    await _login(client, "ketoan@zbridge.vn", "ketoan-password")
    assert (await client.get("/api/customers")).status_code == 200
    assert (await client.patch(f"/api/customers/{uuid.uuid4()}", json={})).status_code == 403
    assert (await client.post(f"/api/customers/{uuid.uuid4()}/messages", json={
        "content": "xin chào"
    })).status_code == 403


async def test_last_user_manager_cannot_be_removed(session_factory) -> None:
    """Reachable via a role that may delete accounts but not administer them."""
    async with session_factory() as db:
        admin = await db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        assert admin is not None
        read_only = await db.scalar(select(Permission).where(Permission.code == USER_READ))
        deleter_role = Role(code="DELETER", name="Chỉ xóa người dùng", is_system=False)
        deleter_role.permissions = [read_only] if read_only else []
        db.add(deleter_role)
        await db.flush()
        actor = User(
            email="deleter@zbridge.vn",
            password_hash=hash_password("deleter-password"),
            role_id=deleter_role.id,
        )
        db.add(actor)
        await db.commit()

        loaded_actor = await get_user(db, actor.id)
        assert USER_UPDATE not in loaded_actor.permission_codes
        with pytest.raises(AppError) as failure:
            await delete_user(db, loaded_actor, admin.id)
        assert failure.value.code == "LAST_USER_MANAGER"
        assert await db.scalar(select(User.id).where(User.id == admin.id)) is not None


async def test_last_user_manager_cannot_remove_permission_from_own_role(client) -> None:
    admin = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    role = await client.post(
        "/api/roles",
        json={
            "name": "Quản trị tùy chỉnh",
            "permissions": ["user:read", "user:update", "role:read", "role:manage"],
        },
    )
    assert role.status_code == 201, role.text
    manager = await client.post(
        "/api/users",
        json={
            "email": "manager@zbridge.vn",
            "password": "manager-password",
            "role_id": role.json()["id"],
        },
    )
    assert manager.status_code == 201, manager.text

    client.cookies.clear()
    await _login(client, "manager@zbridge.vn", "manager-password")
    disabled = await client.patch(
        f"/api/users/{admin['id']}", json={"is_active": False}
    )
    assert disabled.status_code == 200, disabled.text

    lockout = await client.patch(
        f"/api/roles/{role.json()['id']}",
        json={"permissions": ["user:read", "role:read", "role:manage"]},
    )
    assert lockout.status_code == 422
    assert lockout.json()["error"]["code"] == "LAST_USER_MANAGER"

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.permissions import ROLE_MANAGE, ROLE_READ
from app.db.database import get_db
from app.models import User
from app.schemas.api import PermissionResponse, RoleCreate, RoleResponse, RoleUpdate
from app.services.rbac_service import (
    create_role,
    delete_role,
    list_roles,
    permission_catalog,
    update_role,
)

router = APIRouter(prefix="/roles", tags=["roles"])


@router.get("", response_model=list[RoleResponse])
async def index(
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(ROLE_READ)),
) -> list[RoleResponse]:
    return await list_roles(db)


@router.get("/permissions", response_model=list[PermissionResponse])
async def permissions(
    _actor: User = Depends(require_permission(ROLE_READ)),
) -> list[PermissionResponse]:
    return permission_catalog()


@router.post("", response_model=RoleResponse, status_code=201)
async def create(
    data: RoleCreate,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(ROLE_MANAGE)),
) -> RoleResponse:
    return await create_role(db, data)


@router.patch("/{role_id}", response_model=RoleResponse)
async def update(
    role_id: uuid.UUID,
    data: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(ROLE_MANAGE)),
) -> RoleResponse:
    return await update_role(db, role_id, data)


@router.delete("/{role_id}", status_code=204)
async def destroy(
    role_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(ROLE_MANAGE)),
) -> None:
    await delete_role(db, role_id)

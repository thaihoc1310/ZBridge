import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.core.permissions import USER_CREATE, USER_DELETE, USER_READ, USER_UPDATE
from app.db.database import get_db
from app.models import User
from app.schemas.api import UserCreate, UserResponse, UserUpdate
from app.services.user_service import create_user, delete_user, list_users, update_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserResponse])
async def index(
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(USER_READ)),
) -> list[UserResponse]:
    return await list_users(db)


@router.post("", response_model=UserResponse, status_code=201)
async def create(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    _actor: User = Depends(require_permission(USER_CREATE)),
) -> UserResponse:
    return await create_user(db, data)


@router.patch("/{user_id}", response_model=UserResponse)
async def update(
    user_id: uuid.UUID,
    data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(USER_UPDATE)),
) -> UserResponse:
    return await update_user(db, actor, user_id, data)


@router.delete("/{user_id}", status_code=204)
async def destroy(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_permission(USER_DELETE)),
) -> None:
    await delete_user(db, actor, user_id)

"""JWT login routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..conf import get_settings
from ..infrastructure.db.engine import get_session
from ..infrastructure.db.repositories import MembershipRepository, UserRepository
from ..security.auth import create_access_token, verify_password
from .deps import UserPrincipal, require_user

router = APIRouter(prefix="/auth", tags=["auth"])
me_router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    tenant_id: UUID | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: UUID
    email: str
    tenant_id: UUID
    role: str


async def authenticate_user(repo: UserRepository, email: str, password: str):
    user = await repo.get_by_email(email)
    if user is None or user.status != "active":
        return None
    return user if verify_password(password, user.password_hash) else None


async def resolve_membership(
    repo: MembershipRepository, user_id: UUID, tenant_id: UUID | None
):
    memberships = await repo.list_for_user(user_id)
    if tenant_id is not None:
        for membership in memberships:
            if membership.tenant_id == tenant_id:
                return membership
        raise HTTPException(403, "tenant not found")
    if len(memberships) == 1:
        return memberships[0]
    if not memberships:
        raise HTTPException(403, "no tenant membership")
    raise HTTPException(400, "tenant_id required")


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, session: Annotated[AsyncSession, Depends(get_session)]) -> TokenResponse:
    user = await authenticate_user(UserRepository(session), req.email, req.password)
    if user is None:
        raise HTTPException(401, "invalid email or password")

    membership = await resolve_membership(
        MembershipRepository(session), user.id, req.tenant_id
    )
    settings = get_settings()
    token = create_access_token(
        user.id,
        user.email,
        membership.tenant_id,
        membership.role,
        settings.jwt_secret,
        settings.jwt_access_ttl_seconds,
    )
    return TokenResponse(access_token=token, expires_in=settings.jwt_access_ttl_seconds)


@me_router.get("/me", response_model=UserResponse)
async def me(
    principal: Annotated[UserPrincipal, Depends(require_user)],
) -> UserResponse:
    return UserResponse(
        id=principal.user_id,
        email=principal.email,
        tenant_id=principal.tenant_id,
        role=principal.role,
    )

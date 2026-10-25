"""JWT authentication routes."""

import re
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..conf import get_settings
from ..infrastructure.db.engine import get_session
from ..infrastructure.db.models import Membership, Project, Tenant, User
from ..infrastructure.db.repositories import MembershipRepository, UserRepository
from ..security.auth import create_access_token, hash_password, verify_password
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


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    tenant_name: str = Field(min_length=2, max_length=128)


class RegisterResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user_id: UUID
    tenant_id: UUID
    project_id: UUID


async def authenticate_user(repo: UserRepository, email: str, password: str):
    user = await repo.get_by_email(email.strip().lower())
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


def make_slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "tenant"
    return f"{base[:40]}-{uuid4().hex[:8]}"


@router.post("/register", response_model=RegisterResponse, status_code=201)
async def register(
    req: RegisterRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RegisterResponse:
    email = req.email.strip().lower()
    if await UserRepository(session).get_by_email(email) is not None:
        raise HTTPException(409, "email already registered")

    user_id, tenant_id, project_id = uuid4(), uuid4(), uuid4()
    user = User(
        id=user_id,
        email=email,
        password_hash=hash_password(req.password),
        status="active",
    )
    tenant = Tenant(
        id=tenant_id,
        name=req.tenant_name.strip(),
        slug=make_slug(req.tenant_name),
        plan="free",
        status="active",
    )
    membership = Membership(tenant_id=tenant_id, user_id=user_id, role="owner")
    project = Project(
        id=project_id,
        tenant_id=tenant_id,
        name="Default",
        slug="default",
        settings={},
    )
    session.add_all([user, tenant, membership, project])
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "registration conflict") from None

    settings = get_settings()
    token = create_access_token(
        user_id,
        email,
        tenant_id,
        "owner",
        settings.jwt_secret,
        settings.jwt_access_ttl_seconds,
    )
    return RegisterResponse(
        access_token=token,
        expires_in=settings.jwt_access_ttl_seconds,
        user_id=user_id,
        tenant_id=tenant_id,
        project_id=project_id,
    )


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

"""JWT login routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..conf import get_settings
from ..infrastructure.db.engine import get_session
from ..infrastructure.db.repositories import UserRepository
from ..security.auth import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


async def authenticate_user(repo: UserRepository, email: str, password: str):
    user = await repo.get_by_email(email)
    if user is None or user.status != "active":
        return None
    return user if verify_password(password, user.password_hash) else None


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, session: Annotated[AsyncSession, Depends(get_session)]) -> TokenResponse:
    user = await authenticate_user(UserRepository(session), req.email, req.password)
    if user is None:
        raise HTTPException(401, "invalid email or password")

    settings = get_settings()
    token = create_access_token(
        user.id, user.email, settings.jwt_secret, settings.jwt_access_ttl_seconds
    )
    return TokenResponse(access_token=token, expires_in=settings.jwt_access_ttl_seconds)

"""Password hashing and JWT access tokens."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from jwt import InvalidTokenError

ALGORITHM = "HS256"
HASHER = PasswordHasher()


class TokenError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TokenPayload:
    user_id: UUID
    email: str


def hash_password(password: str) -> str:
    return HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return HASHER.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def create_access_token(user_id: UUID, email: str, secret: str, ttl_seconds: int) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        "jti": uuid4().hex,
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(token: str, secret: str) -> TokenPayload:
    try:
        payload = jwt.decode(
            token, secret, algorithms=[ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
        return TokenPayload(UUID(payload["sub"]), payload["email"])
    except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
        raise TokenError("invalid token") from exc

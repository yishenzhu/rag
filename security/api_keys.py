"""API key generation, hashing and scope checks."""

import hashlib
import hmac
import secrets
import string
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

KEY_VERSION = "sk"
KEY_ALPHABET = string.ascii_letters + string.digits
PREFIX_LEN = 8
SECRET_LEN = 32
ENVIRONMENTS = frozenset({"live", "test"})


class Scope(StrEnum):
    MEMORIES_READ = "memories:read"
    MEMORIES_WRITE = "memories:write"
    KNOWLEDGE_READ = "knowledge:read"
    KNOWLEDGE_WRITE = "knowledge:write"
    USAGE_READ = "usage:read"
    ADMIN = "admin"


ALL_SCOPES = frozenset(scope.value for scope in Scope)


class ApiKeyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ApiKeyMaterial:
    """Plaintext is returned once and must never be stored or logged."""

    plaintext: str
    key_prefix: str
    key_hash: str


@dataclass(frozen=True, slots=True)
class ParsedApiKey:
    environment: str
    prefix: str
    secret: str
    key_prefix: str


def random_token(length: int) -> str:
    return "".join(secrets.choice(KEY_ALPHABET) for _ in range(length))


def hash_secret(secret: str, pepper: str) -> str:
    return hmac.new(pepper.encode(), secret.encode(), hashlib.sha256).hexdigest()


def verify_secret(secret: str, expected_hash: str, pepper: str) -> bool:
    return hmac.compare_digest(hash_secret(secret, pepper), expected_hash)


def generate_api_key(pepper: str, environment: str = "live") -> ApiKeyMaterial:
    if not pepper:
        raise ApiKeyError("pepper must not be empty")
    if environment not in ENVIRONMENTS:
        raise ApiKeyError(f"unknown environment: {environment}")
    prefix, secret = random_token(PREFIX_LEN), random_token(SECRET_LEN)
    key_prefix = f"{KEY_VERSION}_{environment}_{prefix}"
    return ApiKeyMaterial(
        plaintext=f"{key_prefix}_{secret}",
        key_prefix=key_prefix,
        key_hash=hash_secret(secret, pepper),
    )


def parse_api_key(plaintext: str) -> ParsedApiKey:
    parts = plaintext.split("_")
    if len(parts) != 4:
        raise ApiKeyError("invalid api key format")

    version, environment, prefix, secret = parts
    if version != KEY_VERSION or environment not in ENVIRONMENTS:
        raise ApiKeyError("invalid api key header")
    if len(prefix) != PREFIX_LEN or len(secret) != SECRET_LEN:
        raise ApiKeyError("invalid api key length")
    key_prefix = f"{version}_{environment}_{prefix}"
    return ParsedApiKey(environment, prefix, secret, key_prefix)


def verify_api_key(plaintext: str, expected_hash: str, pepper: str) -> bool:
    try:
        parsed = parse_api_key(plaintext)
    except ApiKeyError:
        return False
    return verify_secret(parsed.secret, expected_hash, pepper)


def normalize_scopes(scopes: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for scope in scopes:
        value = str(scope)
        if value not in ALL_SCOPES:
            raise ApiKeyError(f"unknown scope: {value}")
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def has_scope(scopes: Iterable[str], required: str) -> bool:
    granted = set(scopes)
    return Scope.ADMIN.value in granted or required in granted

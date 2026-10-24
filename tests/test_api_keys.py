"""API key primitive tests."""

import pytest
from rag.security.api_keys import (
    ApiKeyError,
    Scope,
    generate_api_key,
    has_scope,
    normalize_scopes,
    parse_api_key,
    verify_api_key,
)

PEPPER = "test-pepper"


def test_generate_and_parse():
    material = generate_api_key(PEPPER)
    parsed = parse_api_key(material.plaintext)

    assert parsed.environment == "live"
    assert material.key_prefix == parsed.key_prefix
    assert material.plaintext.startswith(f"{material.key_prefix}_")
    assert len(material.key_hash) == 64


def test_generated_keys_are_unique():
    assert len({generate_api_key(PEPPER).plaintext for _ in range(50)}) == 50


def test_verify_api_key():
    material = generate_api_key(PEPPER, environment="test")

    assert verify_api_key(material.plaintext, material.key_hash, PEPPER)
    assert not verify_api_key(material.plaintext, material.key_hash, "wrong")
    assert not verify_api_key("not-a-key", material.key_hash, PEPPER)


def test_invalid_keys():
    with pytest.raises(ApiKeyError):
        parse_api_key("sk_live_short")
    with pytest.raises(ApiKeyError):
        generate_api_key(PEPPER, environment="prod")
    with pytest.raises(ApiKeyError):
        generate_api_key("")


def test_scopes():
    scopes = normalize_scopes([Scope.MEMORIES_READ, "memories:read", Scope.ADMIN])

    assert scopes == ("memories:read", "admin")
    assert has_scope(scopes, "memories:write")
    assert has_scope(("memories:read",), "memories:read")
    assert not has_scope(("memories:read",), "memories:write")

    with pytest.raises(ApiKeyError):
        normalize_scopes(["unknown"])

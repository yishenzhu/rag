"""SDK tests."""

import json

import httpx
import pytest
from rag.sdk import ApiError, RagClient


def make_client(handler, **kwargs):
    return RagClient("http://api", transport=httpx.MockTransport(handler), **kwargs)


@pytest.mark.asyncio
async def test_register_stores_token_and_sends_payload():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["body"] = request.content.decode()
        return httpx.Response(201, json={"access_token": "tok", "project_id": "p"})

    async with make_client(handler) as client:
        data = await client.register("a@b.c", "password123", "acme")
        assert client.token == "tok"

    assert seen["path"] == "/v1/auth/register"
    assert json.loads(seen["body"])["tenant_name"] == "acme"
    assert data["project_id"] == "p"


@pytest.mark.asyncio
async def test_create_memory_prefers_api_key():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["idem"] = request.headers["idempotency-key"]
        return httpx.Response(201, json={"id": "m1"})

    async with make_client(handler, api_key="sk_live_p_s", token="user") as client:
        memory = await client.create_memory("hello", idempotency_key="k1")

    assert memory["id"] == "m1"
    assert seen == {"auth": "Bearer sk_live_p_s", "idem": "k1"}


@pytest.mark.asyncio
async def test_error_carries_status_and_trace_id():
    def handler(request):
        return httpx.Response(
            429, json={"detail": "rate limited"}, headers={"X-Trace-Id": "abc123"}
        )

    async with make_client(handler, api_key="k") as client:
        with pytest.raises(ApiError) as exc:
            await client.search_memories("q")

    assert exc.value.status_code == 429
    assert exc.value.trace_id == "abc123"
    assert exc.value.detail == {"detail": "rate limited"}

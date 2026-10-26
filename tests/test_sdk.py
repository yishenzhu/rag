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


@pytest.mark.asyncio
async def test_management_calls_use_token():
    seen = {}

    def handler(request):
        seen[request.url.path] = {
            "auth": request.headers["authorization"],
            "body": request.content.decode(),
        }
        if request.url.path == "/v1/projects":
            return httpx.Response(200, json=[{"id": "p1"}])
        return httpx.Response(201, json={"id": "k1", "key": "sk_live_x_y"})

    async with make_client(handler, token="user-token") as client:
        projects = await client.list_projects()
        key = await client.create_api_key("p1", "ci", ["memories:read"])

    assert projects == [{"id": "p1"}]
    assert key["key"] == "sk_live_x_y"
    assert seen["/v1/projects"]["auth"] == "Bearer user-token"
    assert json.loads(seen["/v1/api-keys"]["body"])["scopes"] == ["memories:read"]


@pytest.mark.asyncio
async def test_usage_params():
    seen = {}

    def handler(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json={"totals": {}})

    async with make_client(handler, token="t") as client:
        await client.usage(period="2026-10", group_by="model")

    assert seen["params"] == {"group_by": "model", "period": "2026-10"}


@pytest.mark.asyncio
async def test_memory_read_update_delete():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path, request.content.decode()))
        if request.method == "GET":
            return httpx.Response(200, json={"id": "m1", "content": "hi"})
        if request.method == "PATCH":
            return httpx.Response(200, json={"id": "m1", "content": "new"})
        return httpx.Response(204)

    async with make_client(handler, api_key="k") as client:
        assert (await client.get_memory("m1"))["content"] == "hi"
        assert (await client.update_memory("m1", content="new"))["content"] == "new"
        assert await client.delete_memory("m1") is None

    assert [method for method, _, _ in seen] == ["GET", "PATCH", "DELETE"]
    assert json.loads(seen[1][2]) == {"content": "new"}

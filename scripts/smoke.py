"""End-to-end smoke test against a running API, using the SDK."""

import asyncio
import os
import sys
from uuid import uuid4

import httpx
from rag.sdk import ApiError, RagClient

BASE = os.getenv("API_URL", "http://localhost:8001")
PASSWORD = "secret123"


async def wait_active(client: RagClient, memory_id: str, timeout: int = 30) -> None:
    for _ in range(timeout):
        memory = await client.get_memory(memory_id)
        if memory["status"] == "active":
            return
        await asyncio.sleep(1)
    raise RuntimeError("memory not indexed within 30s; is worker running?")


async def main() -> None:
    email = f"smoke-{uuid4().hex[:8]}@example.com"
    async with RagClient(BASE) as client:
        registered = await client.register(email, PASSWORD, "Smoke")
        print("registered", email)

        project = await client.create_project(
            "smoke-project", slug=f"smoke-{uuid4().hex[:8]}"
        )
        created_key = await client.create_api_key(
            project["id"], "smoke", ["memories:read", "memories:write"]
        )
        print("project and api key created")

        client.api_key = created_key["key"]
        client.token = None

        payload = {"metadata": {"source": "smoke"}}
        memory = await client.create_memory(
            "smoke memory about dark theme", idempotency_key="smoke-1", **payload
        )
        replay = await client.create_memory(
            "smoke memory about dark theme", idempotency_key="smoke-1", **payload
        )
        if replay["id"] != memory["id"]:
            raise RuntimeError("idempotent replay returned a different memory")
        print("memory", memory["id"], "idempotent replay ok")

        await wait_active(client, memory["id"])
        print("memory active")

        results = await client.search_memories("dark theme", top_k=5)
        if not any(item["id"] == memory["id"] for item in results):
            raise RuntimeError("memory not found in search")
        print("search ok:", len(results), "results")

        listed = await client.list_memories(limit=10)
        if not any(item["id"] == memory["id"] for item in listed):
            raise RuntimeError("memory not found in list")
        print("list ok")

        updated = await client.update_memory(
            memory["id"], metadata={"source": "smoke", "tag": "v2"}
        )
        if updated["metadata"].get("tag") != "v2":
            raise RuntimeError("update did not apply")
        print("update ok")

        await client.delete_memory(memory["id"])
        try:
            await client.get_memory(memory["id"])
        except ApiError as exc:
            if exc.status_code != 404:
                raise
            print("delete ok, 404 after delete")
        else:
            raise RuntimeError("deleted memory is still readable")

        client.api_key = None
        client.token = registered["access_token"]
        usage = await client.usage()
        print("usage ok:", usage["totals"])

    with httpx.Client(timeout=10) as raw:
        response = raw.get(f"{BASE}/metrics", headers={"Accept": "text/plain"})
        if "http_requests_total" not in response.text:
            raise RuntimeError("metrics endpoint missing http_requests_total")
        print("metrics ok")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        print("FAIL:", exc)
        sys.exit(1)

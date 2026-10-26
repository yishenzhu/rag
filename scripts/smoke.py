"""End-to-end smoke test against a running API."""

import os
import sys
import time
from uuid import uuid4

import httpx

BASE = os.getenv("API_URL", "http://localhost:8001")
PASSWORD = "secret123"


def call(client, method, path, token=None, **kwargs):
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.request(method, f"{BASE}{path}", headers=headers, **kwargs)
    if response.status_code >= 400:
        print(f"FAIL {method} {path}: {response.status_code} {response.text}")
        sys.exit(1)
    return response


def main() -> None:
    with httpx.Client(timeout=30) as client:
        email = f"smoke-{uuid4().hex[:8]}@example.com"
        reg = call(
            client,
            "POST",
            "/v1/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "tenant_name": "Smoke",
            },
        ).json()
        token, project_id = reg["access_token"], reg["project_id"]
        print("registered", email)

        key = call(
            client,
            "POST",
            "/v1/api-keys",
            token,
            json={
                "name": "smoke",
                "project_id": project_id,
                "scopes": ["memories:read", "memories:write"],
            },
        ).json()["key"]
        print("api key created")

        memory = call(
            client,
            "POST",
            "/v1/memories",
            key,
            json={
                "content": "smoke memory about dark theme",
                "metadata": {"source": "smoke"},
            },
        ).json()
        memory_id = memory["id"]
        print("memory", memory_id, memory["status"])

        for _ in range(30):
            current = call(
                client, "GET", f"/v1/memories/{memory_id}", key
            ).json()
            if current["status"] == "active":
                break
            time.sleep(1)
        else:
            print("FAIL memory not indexed within 30s; is worker running?")
            sys.exit(1)
        print("memory active")

        results = call(
            client,
            "POST",
            "/v1/memories/search",
            key,
            json={"query": "dark theme", "top_k": 5},
        ).json()
        if not any(item["id"] == memory_id for item in results):
            print("FAIL memory not found in search")
            sys.exit(1)
        print("search ok:", len(results), "results")


if __name__ == "__main__":
    main()

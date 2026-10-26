"""Minimal async client for the RAG memory API."""

from __future__ import annotations

from typing import Any, Self

import httpx


class ApiError(Exception):
    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(f"HTTP {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail
        self.request_id: str | None = None
        self.trace_id: str | None = None


class RagClient:
    """Async client for auth and memory endpoints.

    Auth calls use a user token, memory calls use an API key. When both are
    set the API key takes precedence.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        token: str | None = None,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_key = api_key
        self.token = token
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self.client.aclose()

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = dict(extra or {})
        credential = self.api_key or self.token
        if credential:
            headers["Authorization"] = f"Bearer {credential}"
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = await self.client.request(
            method, path, json=json, params=params, headers=self._headers(headers)
        )
        if response.status_code >= 400:
            try:
                detail: Any = response.json()
            except ValueError:
                detail = response.text
            error = ApiError(response.status_code, detail)
            error.request_id = response.headers.get("X-Request-Id")
            error.trace_id = response.headers.get("X-Trace-Id")
            raise error
        if response.status_code == 204:
            return None
        return response.json()

    async def register(
        self, email: str, password: str, tenant_name: str
    ) -> dict[str, Any]:
        data = await self._request(
            "POST",
            "/v1/auth/register",
            json={"email": email, "password": password, "tenant_name": tenant_name},
        )
        self.token = data["access_token"]
        return data

    async def login(
        self, email: str, password: str, tenant_id: str | None = None
    ) -> dict[str, Any]:
        payload = {"email": email, "password": password}
        if tenant_id is not None:
            payload["tenant_id"] = tenant_id
        data = await self._request("POST", "/v1/auth/login", json=payload)
        self.token = data["access_token"]
        return data

    async def create_memory(
        self,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
        external_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"content": content, "metadata": metadata or {}}
        if external_id is not None:
            payload["external_id"] = external_id
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return await self._request(
            "POST", "/v1/memories", json=payload, headers=headers
        )

    async def list_memories(
        self, *, limit: int = 20, offset: int = 0
    ) -> list[dict[str, Any]]:
        return await self._request(
            "GET", "/v1/memories", params={"limit": limit, "offset": offset}
        )

    async def search_memories(
        self, query: str, *, top_k: int = 5
    ) -> list[dict[str, Any]]:
        return await self._request(
            "POST", "/v1/memories/search", json={"query": query, "top_k": top_k}
        )

    async def delete_memory(self, memory_id: str) -> None:
        await self._request("DELETE", f"/v1/memories/{memory_id}")

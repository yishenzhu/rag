"""Trace id response header tests."""

import re

import pytest
from httpx import ASGITransport, AsyncClient
from rag.app.main import create_app


def make_client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_response_has_trace_id():
    async with make_client(create_app()) as client:
        response = await client.get("/health/live")

    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Trace-Id"])


@pytest.mark.asyncio
async def test_incoming_traceparent_is_echoed():
    trace_id = "0af7651916cd43dd8448eb211c80319c"
    headers = {"traceparent": f"00-{trace_id}-b7ad6b7169203331-01"}

    async with make_client(create_app()) as client:
        response = await client.get("/health/live", headers=headers)

    assert response.headers["X-Trace-Id"] == trace_id

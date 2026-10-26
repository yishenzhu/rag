"""Prometheus metrics tests."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from opentelemetry.sdk.trace import TracerProvider
from prometheus_client import REGISTRY
from prometheus_client.openmetrics.exposition import generate_latest
from rag.app.main import create_app
from rag.infrastructure.observability import metrics
from rag.infrastructure.observability.metrics import MetricsMiddleware


def test_metrics_middleware_records_request():
    app = FastAPI()
    app.add_middleware(MetricsMiddleware)

    @app.get("/metrics-test")
    def ping():
        return {"ok": True}

    TestClient(app).get("/metrics-test")
    value = REGISTRY.get_sample_value(
        "http_requests_total",
        {"method": "GET", "route": "/metrics-test", "status": "200", "tenant": "other"},
    )
    assert value == 1


def test_tenant_label_allowlist(monkeypatch):
    monkeypatch.setattr(metrics, "MONITORED_TENANTS", frozenset({"t1"}))
    assert metrics.tenant_label("t1") == "t1"
    assert metrics.tenant_label("t2") == "other"
    assert metrics.tenant_label(None) == "other"


@pytest.mark.asyncio
async def test_metrics_endpoint():
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "http_requests_total" in response.text


@pytest.mark.asyncio
async def test_metrics_exemplar_carries_trace_id():
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        pass

    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("work") as span:
        await MetricsMiddleware(app)(
            {"type": "http", "method": "GET", "path": "/exemplar", "headers": []},
            receive,
            send,
        )

    trace_id = format(span.get_span_context().trace_id, "032x")
    body = generate_latest(REGISTRY).decode()
    assert f'trace_id="{trace_id}"' in body


@pytest.mark.asyncio
async def test_http_metrics_use_allowlisted_tenant(monkeypatch):
    monkeypatch.setattr(metrics, "MONITORED_TENANTS", frozenset({"tenant-a"}))

    async def app(scope, receive, send):
        scope["state"] = {"tenant_id": "tenant-a"}
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        pass

    await MetricsMiddleware(app)(
        {"type": "http", "method": "GET", "path": "/tenant-metric", "headers": []},
        receive,
        send,
    )
    value = REGISTRY.get_sample_value(
        "http_requests_total",
        {
            "method": "GET",
            "route": "/tenant-metric",
            "status": "200",
            "tenant": "tenant-a",
        },
    )
    assert value == 1

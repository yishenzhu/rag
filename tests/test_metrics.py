"""Prometheus metrics tests."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY
from rag.app.main import create_app
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
        {"method": "GET", "route": "/metrics-test", "status": "200"},
    )
    assert value == 1


@pytest.mark.asyncio
async def test_metrics_endpoint():
    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "http_requests_total" in response.text

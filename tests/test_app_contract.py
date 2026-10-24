"""Contract tests for the new application entrypoint."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from rag.app.main import create_app
from rag.app.middleware import RequestContextMiddleware, get_context
from rag.engine import RAGPipeline


def make_client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_live_health_echoes_request_id():
    async with make_client(create_app()) as client:
        response = await client.get(
            "/health/live", headers={"X-Request-Id": "test-123"}
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Request-Id"] == "test-123"


@pytest.mark.asyncio
async def test_v1_health_alias_generates_request_id():
    async with make_client(create_app()) as client:
        response = await client.get("/v1/health/live")

    assert response.status_code == 200
    assert response.headers["X-Request-Id"].startswith("req_")


@pytest.mark.asyncio
async def test_ready_when_pipeline_none_is_503():
    app = create_app()
    # 模拟 lifespan 初始化失败后的状态。
    app.state.pipeline = None

    async with make_client(app) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["reason"] == "pipeline_not_initialized"


@pytest.mark.asyncio
async def test_ready_with_pipeline_instance_is_200():
    app = create_app()
    # 只验证就绪状态，不构造 Qdrant/embedding 客户端。
    app.state.pipeline = object.__new__(RAGPipeline)

    async with make_client(app) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_legacy_router_is_mounted():
    async with make_client(create_app()) as client:
        response = await client.get("/legacy/health")

    assert response.status_code == 200
    assert response.json()["service"] == "rag-api"


@pytest.mark.asyncio
async def test_request_context_is_visible_in_endpoint():
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ctx")
    async def ctx():
        return {"request_id": get_context().request_id}

    async with make_client(app) as client:
        response = await client.get("/ctx", headers={"X-Request-Id": "ctx-1"})

    assert response.json()["request_id"] == "ctx-1"

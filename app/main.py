"""FastAPI application factory.

The legacy routers stay available under /legacy until they are migrated to /v1.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..core import Config, setup_logger
from ..engine import RAGPipeline
from ..routes import router as legacy_router
from .api_key_routes import router as api_key_router
from .auth_routes import me_router
from .auth_routes import router as auth_router
from .health import router as health_router
from .middleware import RequestContextMiddleware

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    conf = Config.load()
    setup_logger(conf.log)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pipeline = None
        try:
            pipeline = await RAGPipeline(conf.rag).initialize()
            # 初始化成功后再对外暴露，失败时 state.pipeline 保持 None。
            pipeline.bind_app(app)
            logger.info("RAG pipeline initialized")
        except Exception:
            # 初始化失败时显式置 None -> readiness 503；
            # 属性缺失则代表未初始化/命名错误，直接抛错。
            app.state.pipeline = None
            logger.exception("RAG pipeline initialization failed")

        try:
            yield
        finally:
            if pipeline is not None:
                await pipeline.close()
                logger.info("RAG pipeline closed")

    app = FastAPI(title="RAG Service", version="2.0.0", lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health_router)
    app.include_router(health_router, prefix="/v1")
    app.include_router(auth_router, prefix="/v1")
    app.include_router(me_router, prefix="/v1")
    app.include_router(api_key_router, prefix="/v1")
    app.include_router(legacy_router, prefix="/legacy")
    return app


app = create_app()

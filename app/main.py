"""FastAPI application factory.

The legacy routers stay available under /legacy until they are migrated to /v1.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from redis.asyncio import Redis

from ..conf import get_settings
from ..core import Config, setup_logger
from ..engine import RAGPipeline
from ..infrastructure.cache.last_used import flush_forever
from ..infrastructure.cache.usage_flush import flush_forever as usage_flush_forever
from ..infrastructure.vector.memory_index import MemoryIndex
from ..routes import router as legacy_router
from .api_key_routes import router as api_key_router
from .auth_routes import me_router
from .auth_routes import router as auth_router
from .health import router as health_router
from .memory_routes import router as memory_router
from .middleware import RequestContextMiddleware
from .project_routes import router as project_router
from .usage_routes import router as usage_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    conf = Config.load()
    settings = get_settings()
    setup_logger(conf.log)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        pipeline = None
        try:
            pipeline = await RAGPipeline(conf.rag).initialize()
            pipeline.bind_app(app)
            memory_index = MemoryIndex(pipeline.store, pipeline.embedding)
            await memory_index.initialize()
            app.state.memory_index = memory_index
            logger.info("RAG pipeline and memory index initialized")
        except Exception:
            # 初始化失败时显式置 None -> readiness 503；
            # 属性缺失则代表未初始化/命名错误，直接抛错。
            app.state.pipeline = None
            app.state.memory_index = None
            logger.exception("RAG pipeline initialization failed")

        flush_task = asyncio.create_task(flush_forever(redis))
        usage_task = asyncio.create_task(usage_flush_forever(redis))
        try:
            yield
        finally:
            for task in (flush_task, usage_task):
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if pipeline is not None:
                await pipeline.close()
                logger.info("RAG pipeline closed")
            await redis.aclose()

    app = FastAPI(title="RAG Service", version="2.0.0", lifespan=lifespan)
    app.state.redis = redis
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health_router)
    app.include_router(health_router, prefix="/v1")
    app.include_router(auth_router, prefix="/v1")
    app.include_router(me_router, prefix="/v1")
    app.include_router(api_key_router, prefix="/v1")
    app.include_router(project_router, prefix="/v1")
    app.include_router(memory_router, prefix="/v1")
    app.include_router(usage_router, prefix="/v1")
    app.include_router(legacy_router, prefix="/legacy")
    return app


app = create_app()

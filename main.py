from contextlib import asynccontextmanager
from fastapi import FastAPI
from .core import Config, setup_logger
from .engine import Pipeline
from .routes import router

conf = Config.load()


@asynccontextmanager
async def lifespan(app: FastAPI):
    pipeline = await Pipeline(conf.rag).attach(app).setup()
    try:
        yield
    finally:
        await pipeline.close()


def main():
    setup_logger(conf.log)

    app = FastAPI(
        title="RAG Service",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.include_router(router)

    import uvicorn

    uvicorn.run(app, host=conf.app.host, port=conf.app.port)


main()

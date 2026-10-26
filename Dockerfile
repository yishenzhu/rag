FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv

WORKDIR /srv
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi "uvicorn[standard]" pydantic pydantic-settings pyyaml \
    qdrant-client httpx markitdown numpy "sqlalchemy[asyncio]" asyncpg alembic \
    pyjwt argon2-cffi aiokafka redis prometheus-client

COPY . /srv/rag
RUN mkdir -p /srv/rag/logs \
    && useradd -m -u 10001 app \
    && chown -R app:app /srv/rag

WORKDIR /srv/rag
USER app
EXPOSE 8001

CMD ["uvicorn", "rag.app.main:app", "--host", "0.0.0.0", "--port", "8001"]

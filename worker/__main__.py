"""Worker entrypoint: Outbox Relay + Memory Consumer."""

import asyncio
import json

from aiokafka import AIOKafkaConsumer
from prometheus_client import start_http_server
from qdrant_client import AsyncQdrantClient

from ..conf import get_settings
from ..core import Config, setup_logger
from ..embedding import EmbeddingClient
from ..infrastructure.db.engine import dispose_engine, get_engine, get_session_factory
from ..infrastructure.db.expiry import expire_forever
from ..infrastructure.db.outbox import TOPIC_MEMORY_DELETE, TOPIC_MEMORY_INGEST
from ..infrastructure.observability.backlog import refresh_backlog_forever
from ..infrastructure.observability.tracing import instrument_engine, setup_tracing
from ..infrastructure.queue.consumer import MemoryConsumer
from ..infrastructure.queue.kafka import KafkaProducer
from ..infrastructure.queue.relay import OutboxRelay
from ..infrastructure.vector.memory_index import MemoryIndex

METRICS_PORT = 8004


async def consume(consumer, session, index, producer) -> None:
    async for message in consumer:
        event = json.loads(message.value)
        for attempt in range(3):
            try:
                await MemoryConsumer(session, index).handle(event)
                break
            except Exception:  # noqa: BLE001
                await session.rollback()
                if attempt == 2:
                    key = message.key.decode() if message.key else ""
                    await producer.send(
                        f"{message.topic}.dlq", key, message.value
                    )
                else:
                    await asyncio.sleep(2**attempt)
        await consumer.commit()


async def main() -> None:
    settings = get_settings()
    conf = Config.load()
    setup_logger(conf.log)
    setup_tracing("rag-worker")
    instrument_engine(get_engine())

    client = AsyncQdrantClient(host=conf.rag.qdrant.host, port=conf.rag.qdrant.port)
    embedder = EmbeddingClient(conf.rag.embedding.server)
    index = MemoryIndex(client, embedder)
    await index.initialize()

    producer = KafkaProducer(settings.kafka_bootstrap_servers)
    consumer = AIOKafkaConsumer(
        TOPIC_MEMORY_INGEST,
        TOPIC_MEMORY_DELETE,
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="rag-memory-worker",
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )

    await producer.start()
    await consumer.start()
    start_http_server(METRICS_PORT)
    factory = get_session_factory()
    try:
        async with factory() as relay_session, factory() as consumer_session:
            await asyncio.gather(
                OutboxRelay(relay_session, producer).run_forever(),
                consume(consumer, consumer_session, index, producer),
                refresh_backlog_forever(),
                expire_forever(),
            )
    finally:
        await consumer.stop()
        await producer.stop()
        await embedder.aclose()
        await client.close()
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())

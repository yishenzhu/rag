"""OpenTelemetry tracing setup."""

import logging
import os

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

TRACES_PATH = "/v1/traces"
configured = False


def traces_endpoint(raw: str) -> str:
    endpoint = raw.rstrip("/")
    return endpoint if endpoint.endswith(TRACES_PATH) else endpoint + TRACES_PATH


def setup_tracing(service_name: str) -> None:
    global configured
    if configured:
        return
    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name})
    )
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=traces_endpoint(endpoint)))
        )
        logger.info("traces exported to %s", traces_endpoint(endpoint))
    trace.set_tracer_provider(provider)
    HTTPXClientInstrumentor().instrument()
    configured = True


def instrument_fastapi(app: FastAPI) -> None:
    FastAPIInstrumentor.instrument_app(app, excluded_urls="/metrics")


def instrument_engine(engine: AsyncEngine) -> None:
    SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)

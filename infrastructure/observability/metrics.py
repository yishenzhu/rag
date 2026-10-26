"""Prometheus metrics and ASGI instrumentation."""

import os
import re
import time

from fastapi import Response
from prometheus_client import REGISTRY, Counter, Gauge, Histogram
from prometheus_client.openmetrics.exposition import (
    CONTENT_TYPE_LATEST,
    generate_latest,
)
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .tracing import current_trace_id

# 只给白名单内的租户打标签，其余归入 other，避免标签基数失控。
MONITORED_TENANTS = frozenset(
    filter(None, os.getenv("METRICS_TENANT_ALLOWLIST", "").split(","))
)


def tenant_label(tenant_id: str | None) -> str:
    if tenant_id and str(tenant_id) in MONITORED_TENANTS:
        return str(tenant_id)
    return "other"


ROUTE_PARAM = re.compile(r"\\?\{[^/}]+\\?\}")


def route_label(scope: Scope) -> str:
    """Return the route template with the include prefix (e.g. /v1/memories/{id}).

    The router stores paths without their include prefix, so the prefix is
    recovered from the tail match against the actual request path.
    """
    route = scope.get("route")
    template = getattr(route, "path", None)
    if template is None:
        return "unmatched"
    path = scope.get("path", "")
    pattern = ROUTE_PARAM.sub("[^/]+", re.escape(template)) + "$"
    match = re.search(pattern, path)
    if match is None:
        return template
    return path[: match.start()] + template


HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests",
    ["method", "route", "status", "tenant"],
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["method", "route", "tenant"],
)
AUTH_FAILURES = Counter(
    "auth_failures_total",
    "Authentication failures",
    ["reason"],
)
RATE_LIMIT_REJECTED = Counter(
    "rate_limit_rejected_total",
    "Rate limited requests",
    ["tenant"],
)
QUOTA_EXCEEDED = Counter(
    "quota_exceeded_total",
    "Quota exceeded requests",
    ["tenant"],
)
USAGE_FLUSH_FAILURES = Counter(
    "usage_flush_failures_total",
    "Usage ledger flush failures",
)
OUTBOX_PUBLISH_FAILURES = Counter(
    "outbox_publish_failures_total",
    "Outbox publish failures",
)
OUTBOX_PENDING = Gauge(
    "outbox_pending",
    "Outbox rows waiting to be published",
)
OUTBOX_OLDEST_PENDING_SECONDS = Gauge(
    "outbox_oldest_pending_seconds",
    "Age of the oldest pending outbox row",
)
MEMORIES_BY_STATUS = Gauge(
    "memories_by_status",
    "Memory rows grouped by status",
    ["status"],
)


def metrics_response() -> Response:
    return Response(
        generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST
    )


class MetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status_code = 500
        trace_id = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, trace_id
            if message["type"] == "http.response.start":
                status_code = message["status"]
                trace_id = current_trace_id()
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            path = route_label(scope)
            method = scope.get("method", "UNKNOWN")
            tenant = tenant_label(scope.get("state", {}).get("tenant_id"))
            exemplar = {"trace_id": trace_id} if trace_id else None
            HTTP_REQUESTS.labels(method, path, str(status_code), tenant).inc(
                exemplar=exemplar
            )
            HTTP_DURATION.labels(method, path, tenant).observe(
                time.perf_counter() - start, exemplar=exemplar
            )

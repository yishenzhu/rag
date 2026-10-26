"""Per-request context plus X-Request-Id / X-Trace-Id propagation."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4

from opentelemetry import trace
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_REQUEST_ID_LEN = 128


@dataclass(slots=True)
class RequestContext:
    request_id: str
    tenant_id: str | None = None
    project_id: str | None = None
    actor_type: str | None = None
    actor_id: str | None = None
    scopes: tuple[str, ...] = ()


context: ContextVar[RequestContext | None] = ContextVar(
    "rag_request_context", default=None
)


def get_context() -> RequestContext:
    """Return the current request context (fallback keeps direct calls safe)."""
    return context.get() or RequestContext(request_id="-")


def current_trace_id() -> str | None:
    span_context = trace.get_current_span().get_span_context()
    return format(span_context.trace_id, "032x") if span_context.is_valid else None


class RequestContextMiddleware:
    """Assign a request id and expose it via contextvar, request.state and header."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        raw = Headers(scope=scope).get("x-request-id", "").strip()
        request_id = (raw or f"req_{uuid4().hex}")[:MAX_REQUEST_ID_LEN]
        token = context.set(RequestContext(request_id=request_id))
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-Id"] = request_id
                trace_id = current_trace_id()
                if trace_id is not None:
                    headers["X-Trace-Id"] = trace_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            context.reset(token)

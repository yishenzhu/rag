"""Per-request context and X-Request-Id propagation."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from uuid import uuid4

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
                MutableHeaders(scope=message)["X-Request-Id"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            context.reset(token)

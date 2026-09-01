"""Request-ID propagation + structured request logging.

Every request gets an `X-Request-ID` (client-supplied or generated), bound into
structlog's contextvars so every log line emitted while handling the request carries
it automatically, and echoed back on the response so a client-reported bug is traceable.
"""

import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = round((time.perf_counter() - start) * 1000, 2)

        response.headers[REQUEST_ID_HEADER] = request_id

        logger.info(
            "request_completed",
            route=request.url.path,
            method=request.method,
            status_code=response.status_code,
            latency_ms=latency_ms,
            user_id=getattr(request.state, "user_id", None),
        )
        return response

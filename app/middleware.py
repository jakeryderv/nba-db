"""HTTP policy middleware for telemetry, security headers, and rate limiting."""

from __future__ import annotations

import logging
import os
import re
import threading
from collections import defaultdict, deque
from time import monotonic, perf_counter
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

logger = logging.getLogger("uvicorn.error")

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)
EXPENSIVE_PATHS = {"/api/shot-chart", "/api/shot-profile", "/api/shot-chart.csv"}


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


class SlidingWindowLimiter:
    """Small process-local limiter suitable for the app's single Railway replica."""

    def __init__(self, window_seconds: int = 60) -> None:
        self.window_seconds = window_seconds
        self._requests: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(
        self, client: str, group: str, limit: int, now: float | None = None
    ) -> tuple[bool, int]:
        current = monotonic() if now is None else now
        cutoff = current - self.window_seconds
        key = (client, group)
        with self._lock:
            requests = self._requests[key]
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= limit:
                retry_after = max(1, int(self.window_seconds - (current - requests[0])) + 1)
                return False, retry_after
            requests.append(current)
            return True, 0


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if forwarded:
        return forwarded[:100]
    return request.client.host[:100] if request.client else "unknown"


def _apply_response_policy(request: Request, response: Response, elapsed_ms: float) -> None:
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    revision = os.getenv("RAILWAY_GIT_COMMIT_SHA", "development")
    if revision == "development" or re.fullmatch(r"[0-9a-f]{7,40}", revision):
        response.headers["X-Release-Revision"] = revision
    if request.method == "GET" and response.status_code < 400:
        if request.url.path == "/health":
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path == "/":
            response.headers["Cache-Control"] = "no-cache"
        elif request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=3600, must-revalidate"
        elif request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=3600"


class RequestPolicyMiddleware(BaseHTTPMiddleware):
    """Apply bounded public-API access, request correlation, and response policy."""

    def __init__(self, app: object) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.enabled = os.getenv("RATE_LIMIT_ENABLED", "true").lower() not in {"0", "false", "no"}
        self.general_limit = _positive_int("RATE_LIMIT_REQUESTS", 600)
        self.expensive_limit = _positive_int("RATE_LIMIT_EXPENSIVE_REQUESTS", 120)
        self.limiter = SlidingWindowLimiter(_positive_int("RATE_LIMIT_WINDOW_SECONDS", 60))

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = perf_counter()
        supplied_request_id = request.headers.get("X-Request-ID", "")
        request.state.request_id = (
            supplied_request_id
            if re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", supplied_request_id)
            else uuid4().hex
        )

        limited_api_request = request.url.path.startswith("/api/") and (
            request.method == "GET" or request.url.path == "/api/telemetry"
        )
        if self.enabled and limited_api_request:
            group = "expensive" if request.url.path in EXPENSIVE_PATHS else "api"
            limit = self.expensive_limit if group == "expensive" else self.general_limit
            allowed, retry_after = self.limiter.check(_client_key(request), group, limit)
            if not allowed:
                response: Response = JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded; retry later"},
                    headers={"Retry-After": str(retry_after)},
                )
                _apply_response_policy(request, response, (perf_counter() - started) * 1000)
                return response

        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Unhandled request request_id=%s method=%s path=%s",
                request.state.request_id,
                request.method,
                request.url.path,
            )
            raise

        elapsed_ms = (perf_counter() - started) * 1000
        _apply_response_policy(request, response, elapsed_ms)
        log = logger.warning if elapsed_ms >= 1000 else logger.info
        log(
            "Request request_id=%s method=%s path=%s duration_ms=%.1f status=%s",
            request.state.request_id,
            request.method,
            request.url.path,
            elapsed_ms,
            response.status_code,
        )
        return response

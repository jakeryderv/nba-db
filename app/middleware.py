"""HTTP policy middleware for telemetry, security headers, and rate limiting."""

from __future__ import annotations

import ipaddress
import logging
import os
import re
import threading
from collections import OrderedDict, deque
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
PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), payment=(), usb=()"
)
STRICT_TRANSPORT_SECURITY = "max-age=31536000; includeSubDomains"
EXPENSIVE_PATHS = {"/api/shot-chart", "/api/shot-profile", "/api/shot-chart.csv"}

# Railway reaches the container from this range for internal probes.
CARRIER_GRADE_NAT = ipaddress.ip_network("100.64.0.0/10")
# Longest textual IPv6 form, including an IPv4-mapped tail.
MAX_ADDRESS_LENGTH = 45

# Rate limiting is default-on for the whole surface. Anything not limited is
# named here, so a new route is covered the day it is added rather than by
# whether it happens to sit under a particular prefix.
EXEMPT_PATHS = {"/health"}
EXEMPT_PREFIXES = ("/static/",)

# Readiness gets its own budget rather than sharing the general one: Railway's
# healthcheck reads it, and a flood against the rest of the surface must not be
# able to spend the budget the platform needs to keep the release healthy.
READINESS_PATHS = {"/ready"}


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


class SlidingWindowLimiter:
    """Small process-local limiter suitable for the app's single Railway replica."""

    # How many least-recently-used entries to reclaim per call. Bounded so a
    # request never pays for a full sweep of the table.
    _EVICTION_BUDGET = 8

    def __init__(self, window_seconds: int = 60, max_keys: int = 10_000) -> None:
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        # Ordered least- to most-recently used, so reclaiming from the front
        # takes the entries most likely to have aged out.
        self._requests: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()
        self._lock = threading.Lock()
        self._capacity_warned = False

    @property
    def tracked_keys(self) -> int:
        """Number of client/group entries currently held."""
        with self._lock:
            return len(self._requests)

    def _reclaim(self, cutoff: float) -> None:
        """Drop least-recently-used keys whose windows have fully drained."""
        for _ in range(self._EVICTION_BUDGET):
            if not self._requests:
                return
            key = next(iter(self._requests))
            requests = self._requests[key]
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if requests:
                # The least-recently-used entry is still active, so nothing
                # older remains to reclaim.
                return
            del self._requests[key]

    def check(
        self, client: str, group: str, limit: int, now: float | None = None
    ) -> tuple[bool, int]:
        current = monotonic() if now is None else now
        cutoff = current - self.window_seconds
        key = (client, group)
        with self._lock:
            self._reclaim(cutoff)
            requests = self._requests.get(key)
            if requests is None:
                requests = deque()
                self._requests[key] = requests
            else:
                self._requests.move_to_end(key)
                while requests and requests[0] <= cutoff:
                    requests.popleft()
            if len(requests) >= limit:
                retry_after = max(1, int(self.window_seconds - (current - requests[0])) + 1)
                return False, retry_after
            requests.append(current)
            # A hard cap backstops the reclaim pass against a flood of distinct
            # keys. Evicting the least-recently-used entry keeps limiting in
            # force; refusing new keys instead would let anyone who fills the
            # table deny service to everyone else.
            while len(self._requests) > self.max_keys:
                self._requests.popitem(last=False)
                if not self._capacity_warned:
                    self._capacity_warned = True
                    logger.warning(
                        "Rate limiter reached its %d-key cap; evicting least-recently-used clients",
                        self.max_keys,
                    )
            return True, 0


def _proxy_attributed_client(request: Request) -> str | None:
    """Return the client address the nearest proxy attributes, if it set one.

    Cloudflare overwrites CF-Connecting-IP on every proxied request, so unlike a
    position within X-Forwarded-For it cannot be supplied by the caller at all.
    It is also stable across topology changes: adding a proxy layer shifts which
    position in the chain holds the client, but not this header.

    Anything that does not parse as an address is ignored rather than used, so a
    malformed value falls through to the positional derivation instead of
    becoming a key of its own.
    """
    value = request.headers.get("cf-connecting-ip", "").strip()
    if not value or len(value) > MAX_ADDRESS_LENGTH:
        return None
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return None
    return value


def _client_key(request: Request, trusted_hops: int = 1) -> str:
    """Identify the caller by an address they cannot choose.

    Preference order: the address the nearest proxy attributes, then the hop the
    trusted edge appended, then the peer.

    Each proxy appends the peer it received the request from, so a caller can
    prepend entries to X-Forwarded-For but cannot append past the edge. Reading
    from the right is therefore the only way to get a value the caller does not
    control; the leftmost value -- which uvicorn's proxy-header handling also
    returns when it trusts every host -- is caller-chosen and useless as a key.

    This assumes ingress always passes through the trusted edge, which holds on
    Railway: the public domain routes through the edge proxy and the service is
    not otherwise publicly reachable. If the app is ever exposed directly, a
    caller could supply the whole chain and this derivation stops being sound.
    """
    attributed = _proxy_attributed_client(request)
    if attributed:
        return attributed

    peer = request.client.host if request.client else ""
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    # Only report on the positional path: it is the only one whose correctness
    # depends on the configured depth.
    _observe_forwarding(len(hops), trusted_hops, peer)
    if len(hops) >= trusted_hops >= 1:
        return hops[-trusted_hops][:100]
    # No header, or a chain shorter than the expected proxy depth: the header
    # is absent or forged, so fall back to the peer we can actually observe.
    return peer[:100] if peer else "unknown"


_forwarding_observed = False


def _is_internal_peer(host: str) -> bool:
    """Whether a peer address belongs to the platform rather than the internet.

    Railway's readiness prober reaches the container directly, from the
    carrier-grade NAT range, and so legitimately carries no forwarding header.
    """
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    return address.version == 4 and address in CARRIER_GRADE_NAT


def _observe_forwarding(chain_length: int, trusted_hops: int, peer: str) -> None:
    """Report the forwarding depth once, and warn whenever it is too short.

    The hop count is a deployment fact this code cannot verify for itself. The
    first public request records the depth actually observed, so the configured
    value can be checked against production rather than assumed; a chain shorter
    than the configured depth means the limiter is falling back to the peer
    address and every caller is sharing one budget.

    Internal probes are excluded from both. They have no forwarding header by
    design, so warning about them would assert a degradation that is not
    happening -- and since a probe is usually the very first request an instance
    serves, it would otherwise be the one request the depth is reported from.
    """
    global _forwarding_observed
    if _is_internal_peer(peer):
        return
    if not _forwarding_observed:
        _forwarding_observed = True
        logger.info(
            "Forwarded-for depth observed: chain_length=%d trusted_hops=%d",
            chain_length,
            trusted_hops,
        )
    if chain_length < trusted_hops:
        logger.warning(
            "Forwarded-for chain shorter than TRUSTED_PROXY_HOPS "
            "(chain_length=%d trusted_hops=%d); rate limiting is keyed on the peer address",
            chain_length,
            trusted_hops,
        )


def _apply_response_policy(request: Request, response: Response, elapsed_ms: float) -> None:
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
    response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Strict-Transport-Security"] = STRICT_TRANSPORT_SECURITY
    response.headers["Permissions-Policy"] = PERMISSIONS_POLICY
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


def apply_error_policy(request: Request, response: Response) -> None:
    """Apply response policy to a response built outside the middleware stack.

    Starlette's ServerErrorMiddleware sits outside this middleware, so a
    response produced by the catch-all exception handler never passes back
    through dispatch and would otherwise ship without security headers.
    """
    if not getattr(request.state, "request_id", ""):
        request.state.request_id = uuid4().hex
    _apply_response_policy(request, response, 0.0)


class RequestPolicyMiddleware(BaseHTTPMiddleware):
    """Apply bounded public-API access, request correlation, and response policy."""

    def __init__(self, app: object) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.enabled = os.getenv("RATE_LIMIT_ENABLED", "true").lower() not in {"0", "false", "no"}
        self.general_limit = _positive_int("RATE_LIMIT_REQUESTS", 600)
        self.expensive_limit = _positive_int("RATE_LIMIT_EXPENSIVE_REQUESTS", 120)
        self.readiness_limit = _positive_int("RATE_LIMIT_READY_REQUESTS", 600)
        # One trusted hop: Railway's edge. Configurable so the position can be
        # corrected without a code change if the edge topology differs.
        self.trusted_hops = _positive_int("TRUSTED_PROXY_HOPS", 1)
        self.limiter = SlidingWindowLimiter(
            _positive_int("RATE_LIMIT_WINDOW_SECONDS", 60),
            max_keys=_positive_int("RATE_LIMIT_MAX_CLIENTS", 10_000),
        )

    def _limit_group(self, path: str) -> tuple[str, int] | None:
        """Classify a path for limiting, or None when it is exempt."""
        if path in EXEMPT_PATHS or path.startswith(EXEMPT_PREFIXES):
            return None
        if path in READINESS_PATHS:
            return "ready", self.readiness_limit
        if path in EXPENSIVE_PATHS:
            return "expensive", self.expensive_limit
        return "general", self.general_limit

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        started = perf_counter()
        supplied_request_id = request.headers.get("X-Request-ID", "")
        request.state.request_id = (
            supplied_request_id
            if re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", supplied_request_id)
            else uuid4().hex
        )

        classification = self._limit_group(request.url.path) if self.enabled else None
        if classification is not None:
            group, limit = classification
            allowed, retry_after = self.limiter.check(
                _client_key(request, self.trusted_hops), group, limit
            )
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

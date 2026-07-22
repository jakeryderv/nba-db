"""HTTP policy and bounded-rate behavior."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware import SlidingWindowLimiter


def test_sliding_window_limiter_rejects_then_recovers() -> None:
    limiter = SlidingWindowLimiter(window_seconds=60)

    assert limiter.check("client", "expensive", 2, now=100) == (True, 0)
    assert limiter.check("client", "expensive", 2, now=101) == (True, 0)
    allowed, retry_after = limiter.check("client", "expensive", 2, now=102)
    assert allowed is False
    assert retry_after == 59
    assert limiter.check("client", "expensive", 2, now=161) == (True, 0)


def test_limiter_keeps_api_groups_independent() -> None:
    limiter = SlidingWindowLimiter(window_seconds=60)

    assert limiter.check("client", "api", 1, now=100) == (True, 0)
    assert limiter.check("client", "expensive", 1, now=100) == (True, 0)


def test_request_policy_returns_bounded_429(monkeypatch) -> None:
    from app.middleware import RequestPolicyMiddleware

    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    application = FastAPI()
    application.add_middleware(RequestPolicyMiddleware)

    @application.get("/api/example")
    def example() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(application) as client:
        assert client.get("/api/example").status_code == 200
        limited = client.get("/api/example")

    assert limited.status_code == 429
    assert limited.headers["retry-after"]
    assert limited.headers["x-request-id"]
    assert limited.json() == {"detail": "Rate limit exceeded; retry later"}

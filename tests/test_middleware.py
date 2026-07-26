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


def test_telemetry_posts_share_the_bounded_api_budget(monkeypatch) -> None:
    from app.middleware import RequestPolicyMiddleware

    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    application = FastAPI()
    application.add_middleware(RequestPolicyMiddleware)

    @application.post("/api/telemetry", status_code=204)
    def telemetry() -> None:
        return None

    with TestClient(application) as client:
        assert client.post("/api/telemetry").status_code == 204
        limited = client.post("/api/telemetry")

    assert limited.status_code == 429


def _limited_app(monkeypatch, path: str = "/api/example", env: dict[str, str] | None = None):
    """Build an app whose single route is rate limited to one request."""
    from app.middleware import RequestPolicyMiddleware

    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    for name, value in (env or {}).items():
        monkeypatch.setenv(name, value)
    application = FastAPI()
    application.add_middleware(RequestPolicyMiddleware)

    @application.get(path)
    def route() -> dict[str, bool]:
        return {"ok": True}

    return application


def test_forged_forwarding_values_share_one_budget(monkeypatch) -> None:
    """A caller varying X-Forwarded-For must not mint a fresh budget.

    The header is written as the app receives it in production: whatever the
    caller sent, with the edge's observation of the real peer appended.
    """
    application = _limited_app(monkeypatch)

    with TestClient(application) as client:
        first = client.get("/api/example", headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.7"})
        second = client.get("/api/example", headers={"X-Forwarded-For": "9.9.9.9, 203.0.113.7"})

    assert first.status_code == 200
    assert second.status_code == 429


def test_distinct_clients_keep_independent_budgets(monkeypatch) -> None:
    application = _limited_app(monkeypatch)

    with TestClient(application) as client:
        first = client.get("/api/example", headers={"X-Forwarded-For": "203.0.113.7"})
        second = client.get("/api/example", headers={"X-Forwarded-For": "203.0.113.8"})

    assert first.status_code == 200
    assert second.status_code == 200


def test_limiter_reclaims_keys_whose_window_drained() -> None:
    limiter = SlidingWindowLimiter(window_seconds=60)

    limiter.check("stale", "general", 5, now=100)
    assert limiter.tracked_keys == 1

    # A later request from someone else drains and drops the idle entry rather
    # than leaving an empty deque behind forever.
    limiter.check("active", "general", 5, now=200)
    assert limiter.tracked_keys == 1


def test_limiter_cap_evicts_without_disabling_limiting() -> None:
    limiter = SlidingWindowLimiter(window_seconds=60, max_keys=2)

    for index in range(5):
        # Same instant, so nothing ages out and only the cap can bound growth.
        assert limiter.check(f"client-{index}", "general", 1, now=100) == (True, 0)

    assert limiter.tracked_keys <= 2
    # Limiting still applies to whoever remains tracked.
    assert limiter.check("client-4", "general", 1, now=100)[0] is False


def test_paths_outside_the_api_prefix_are_limited(monkeypatch) -> None:
    application = _limited_app(monkeypatch, path="/some-new-route")

    with TestClient(application) as client:
        assert client.get("/some-new-route").status_code == 200
        assert client.get("/some-new-route").status_code == 429


def test_exempt_paths_are_not_limited(monkeypatch) -> None:
    application = _limited_app(monkeypatch, path="/health")

    with TestClient(application) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200


def test_readiness_budget_is_separate_from_general_traffic(monkeypatch) -> None:
    """A flood against the rest of the surface must not throttle the healthcheck."""
    from app.middleware import RequestPolicyMiddleware

    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("RATE_LIMIT_READY_REQUESTS", "5")
    application = FastAPI()
    application.add_middleware(RequestPolicyMiddleware)

    @application.get("/api/example")
    def example() -> dict[str, bool]:
        return {"ok": True}

    @application.get("/ready")
    def ready() -> dict[str, str]:
        return {"status": "ready"}

    with TestClient(application) as client:
        assert client.get("/api/example").status_code == 200
        assert client.get("/api/example").status_code == 429
        for _ in range(5):
            assert client.get("/ready").status_code == 200


def test_security_headers_are_applied(monkeypatch) -> None:
    application = _limited_app(monkeypatch)

    with TestClient(application) as client:
        response = client.get("/api/example")

    assert response.headers["strict-transport-security"] == "max-age=31536000; includeSubDomains"
    assert "camera=()" in response.headers["permissions-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_short_forwarding_chain_is_reported(monkeypatch, caplog) -> None:
    """A chain shorter than the configured depth means every caller shares a budget."""
    import app.middleware as mw

    monkeypatch.setattr(mw, "_forwarding_observed", False)
    application = _limited_app(monkeypatch, env={"TRUSTED_PROXY_HOPS": "2"})

    with caplog.at_level("INFO", logger="uvicorn.error"), TestClient(application) as client:
        client.get("/api/example", headers={"X-Forwarded-For": "203.0.113.7"})

    messages = [record.getMessage() for record in caplog.records]
    assert any("chain_length=1 trusted_hops=2" in message for message in messages)
    assert any("keyed on the peer address" in message for message in messages)

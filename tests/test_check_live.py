"""Tests for bounded deployed-product verification."""

from typing import Any

import pytest

from scripts.check_live import LiveCheckError, check_live


class FakeResponse:
    def __init__(self, body: Any, status: int = 200):
        self.body = body
        self.status_code = status
        self.headers = {
            "X-Request-ID": "test-request",
            "X-Response-Time-Ms": "1.0",
            "X-Content-Type-Options": "nosniff",
        }

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self.body


def _responses() -> dict[str, Any]:
    counts = {"games": 1230, "players": 5204, "shot_attempts": 219160}
    return {
        "/health": {"status": "healthy", "database": "connected"},
        "/ready": {
            "status": "ready",
            "season": "2025-26",
            "verification_status": "passed",
            "counts": counts,
        },
        "/api/dataset-status": {
            "season": "2025-26",
            "verification_status": "passed",
            "counts": counts,
            "manifest_sha256": "abc123",
        },
        "/api/standings": [{"team_id": 1}],
        "/api/leaders/points": {"data": [{"player_id": 1}]},
        "/api/games": {"total": 1230, "data": [{"id": "1"}]},
        "/api/teams": [{"id": 1}],
        "/api/shot-chart": {"subject_id": 1, "zones": [{"zone_basic": "Restricted Area"}]},
    }


def test_live_check_verifies_complete_deployed_contract() -> None:
    bodies = _responses()

    def get(url: str, **_kwargs: Any) -> FakeResponse:
        return FakeResponse(bodies[url.removeprefix("https://nba.example")])

    result = check_live(
        "https://nba.example",
        expected={"games": 1230, "shot_attempts": 219160},
        get=get,
    )

    assert result["status"] == "passed"
    assert result["counts"]["players"] == 5204
    assert "shot_chart" in result["timings_ms"]


def test_live_check_fails_closed_on_count_drift() -> None:
    bodies = _responses()

    def get(url: str, **_kwargs: Any) -> FakeResponse:
        return FakeResponse(bodies[url.removeprefix("https://nba.example")])

    with pytest.raises(LiveCheckError, match="Expected 1231 games"):
        check_live("https://nba.example", expected={"games": 1231}, get=get)


def test_live_check_requires_telemetry_headers() -> None:
    bodies = _responses()

    def get(url: str, **_kwargs: Any) -> FakeResponse:
        response = FakeResponse(bodies[url.removeprefix("https://nba.example")])
        response.headers = {}
        return response

    with pytest.raises(LiveCheckError, match="missing x-request-id"):
        check_live("https://nba.example", get=get)


@pytest.mark.parametrize(
    "url",
    ["http://nba.example", "https://user:secret@nba.example", "nba.example"],
)
def test_live_check_requires_safe_https_url(url: str) -> None:
    with pytest.raises(LiveCheckError, match="credential-free HTTPS"):
        check_live(url, get=lambda *_args, **_kwargs: None)

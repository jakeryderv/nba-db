#!/usr/bin/env python3
"""Bounded live verification for the deployed single-season product."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nba_config import DEFAULT_SEASON  # noqa: E402


class LiveCheckError(RuntimeError):
    """Raised when the deployed product fails a launch-readiness assertion."""


def _expected_count(name: str) -> int | None:
    value = os.getenv(f"EXPECTED_{name.upper()}")
    return int(value) if value else None


def check_live(
    api_url: str,
    season: str = DEFAULT_SEASON,
    *,
    expected: dict[str, int | None] | None = None,
    max_response_ms: float = 3000,
    get: Callable[..., Any] = requests.get,
) -> dict[str, Any]:
    parsed = urlparse(api_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise LiveCheckError("API_URL must be a credential-free HTTPS URL")
    base = api_url.rstrip("/")
    options = {
        "timeout": 10,
        "headers": {"Cache-Control": "no-cache", "Pragma": "no-cache"},
    }

    responses: dict[str, Any] = {}
    timings_ms: dict[str, float] = {}
    for name, path, params in (
        ("health", "/health", None),
        ("ready", "/ready", None),
        ("dataset", "/api/dataset-status", {"season": season}),
        ("standings", "/api/standings", {"season": season}),
        ("leaders", "/api/leaders/points", {"season": season, "limit": 1}),
        ("games", "/api/games", {"season": season, "limit": 1}),
        ("teams", "/api/teams", None),
    ):
        try:
            started = perf_counter()
            response = get(f"{base}{path}", params=params, **options)
            timings_ms[name] = (perf_counter() - started) * 1000
            response.raise_for_status()
        except Exception as exc:
            raise LiveCheckError(f"{name} request failed") from exc
        responses[name] = response.json()
        if timings_ms[name] > max_response_ms:
            raise LiveCheckError(f"{name} exceeded {max_response_ms:.0f}ms response budget")

        headers = getattr(response, "headers", None)
        if headers is not None:
            normalized = {str(key).lower(): value for key, value in headers.items()}
            for required_header in ("x-request-id", "x-response-time-ms", "x-content-type-options"):
                if required_header not in normalized:
                    raise LiveCheckError(f"{name} response is missing {required_header}")

    if responses["health"] != {"status": "healthy", "database": "connected"}:
        raise LiveCheckError("Health response is not healthy")
    ready = responses["ready"]
    dataset = responses["dataset"]
    if ready.get("status") != "ready" or ready.get("season") != season:
        raise LiveCheckError("Readiness response does not match the expected season")
    if dataset.get("season") != season or dataset.get("verification_status") != "passed":
        raise LiveCheckError("Dataset is not officially verified")
    for key in ("games", "players", "shot_attempts"):
        if ready.get("counts", {}).get(key) != dataset.get("counts", {}).get(key):
            raise LiveCheckError(f"Readiness and dataset counts disagree for {key}")
    for key, count in (expected or {}).items():
        if count is not None and dataset.get("counts", {}).get(key) != count:
            raise LiveCheckError(f"Expected {count} {key}, found {dataset['counts'].get(key)}")
    if not responses["standings"] or not responses["leaders"].get("data"):
        raise LiveCheckError("Core exploration endpoints returned no data")
    if responses["games"].get("total") != dataset["counts"]["games"]:
        raise LiveCheckError("Games endpoint total does not match dataset metadata")
    if not responses["teams"]:
        raise LiveCheckError("Teams endpoint returned no data")

    team_id = responses["teams"][0]["id"]
    try:
        started = perf_counter()
        shot_response = get(
            f"{base}/api/shot-chart",
            params={"season": season, "team_id": team_id, "max_points": 100},
            **options,
        )
        timings_ms["shot_chart"] = (perf_counter() - started) * 1000
        shot_response.raise_for_status()
    except Exception as exc:
        raise LiveCheckError("shot_chart request failed") from exc
    if timings_ms["shot_chart"] > max_response_ms:
        raise LiveCheckError(f"shot_chart exceeded {max_response_ms:.0f}ms response budget")
    shot_chart = shot_response.json()
    if shot_chart.get("subject_id") != team_id or not shot_chart.get("zones"):
        raise LiveCheckError("Shot-chart endpoint returned an invalid team profile")

    return {
        "status": "passed",
        "season": season,
        "counts": dataset["counts"],
        "manifest_sha256": dataset.get("manifest_sha256"),
        "timings_ms": {key: round(value, 1) for key, value in timings_ms.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default=os.getenv("LIVE_API_URL"))
    parser.add_argument("--season", default=DEFAULT_SEASON)
    parser.add_argument(
        "--max-response-ms",
        type=float,
        default=float(os.getenv("MAX_RESPONSE_MS", "3000")),
    )
    args = parser.parse_args()
    if not args.api_url:
        parser.error("set LIVE_API_URL or pass --api-url")
    try:
        result = check_live(
            args.api_url,
            args.season,
            expected={
                "games": _expected_count("games"),
                "players": _expected_count("players"),
                "shot_attempts": _expected_count("shot_attempts"),
            },
            max_response_ms=args.max_response_ms,
        )
    except LiveCheckError as exc:
        parser.exit(1, f"Live check failed: {exc}\n")
    print(
        f"Live check passed: {result['season']} · "
        f"{result['counts']['games']} games · "
        f"{result['counts']['shot_attempts']} shots · "
        f"max {max(result['timings_ms'].values()):.1f}ms · manifest {result['manifest_sha256']}"
    )


if __name__ == "__main__":
    main()

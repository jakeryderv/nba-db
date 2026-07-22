#!/usr/bin/env python3
"""Wait for a specific Git revision to become healthy on the public API."""

from __future__ import annotations

import argparse
import re
from collections.abc import Callable
from time import sleep
from typing import Any
from urllib.parse import urlparse

import requests


class ReleaseCheckError(RuntimeError):
    """Raised when the expected release does not become healthy in time."""


def wait_for_release(
    api_url: str,
    expected_revision: str,
    *,
    attempts: int = 60,
    interval_seconds: float = 10,
    get: Callable[..., Any] = requests.get,
    pause: Callable[[float], None] = sleep,
) -> dict[str, str]:
    parsed = urlparse(api_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ReleaseCheckError("API URL must be credential-free HTTPS")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_revision):
        raise ReleaseCheckError("Expected revision must be a full lowercase Git SHA")
    if attempts <= 0 or interval_seconds < 0:
        raise ReleaseCheckError("Attempts must be positive and interval must not be negative")

    health_url = f"{api_url.rstrip('/')}/health"
    last_observation = "no response"
    for attempt in range(attempts):
        try:
            response = get(
                health_url,
                timeout=10,
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            )
            revision = response.headers.get("X-Release-Revision", "missing")
            last_observation = f"HTTP {response.status_code}, revision {revision}"
            if response.status_code == 200 and revision == expected_revision:
                body = response.json()
                if body == {"status": "healthy", "database": "connected"}:
                    return {"status": "healthy", "revision": revision}
        except Exception as exc:
            last_observation = type(exc).__name__
        if attempt + 1 < attempts:
            pause(interval_seconds)

    raise ReleaseCheckError(
        f"Expected release {expected_revision[:12]} did not become healthy "
        f"after {attempts} attempts; last observation: {last_observation}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--expected-revision", required=True)
    parser.add_argument("--attempts", type=int, default=60)
    parser.add_argument("--interval-seconds", type=float, default=10)
    args = parser.parse_args()
    try:
        result = wait_for_release(
            args.api_url,
            args.expected_revision,
            attempts=args.attempts,
            interval_seconds=args.interval_seconds,
        )
    except ReleaseCheckError as exc:
        parser.exit(1, f"Release check failed: {exc}\n")
    print(f"Release is live and healthy: {result['revision']}")


if __name__ == "__main__":
    main()

"""Tests for the bounded public release observer."""

from typing import Any

import pytest

from scripts.check_release import ReleaseCheckError, wait_for_release


class FakeResponse:
    def __init__(self, revision: str, status: int = 200) -> None:
        self.status_code = status
        self.headers = {"X-Release-Revision": revision}

    def json(self) -> dict[str, str]:
        return {"status": "healthy", "database": "connected"}


def test_release_observer_waits_for_the_expected_revision() -> None:
    expected = "a" * 40
    responses = iter([FakeResponse("b" * 40), FakeResponse(expected)])
    pauses: list[float] = []

    result = wait_for_release(
        "https://nba.example",
        expected,
        attempts=2,
        interval_seconds=0.5,
        get=lambda *_args, **_kwargs: next(responses),
        pause=pauses.append,
    )

    assert result == {"status": "healthy", "revision": expected}
    assert pauses == [0.5]


def test_release_observer_fails_closed_on_stale_deployment() -> None:
    with pytest.raises(ReleaseCheckError, match="did not become healthy"):
        wait_for_release(
            "https://nba.example",
            "a" * 40,
            attempts=1,
            interval_seconds=0,
            get=lambda *_args, **_kwargs: FakeResponse("b" * 40),
        )


@pytest.mark.parametrize(
    ("url", "revision"),
    [
        ("http://nba.example", "a" * 40),
        ("https://user:secret@nba.example", "a" * 40),
        ("https://nba.example", "short"),
    ],
)
def test_release_observer_rejects_unsafe_inputs(url: str, revision: str) -> None:
    with pytest.raises(ReleaseCheckError):
        wait_for_release(url, revision, get=lambda *_args, **_kwargs: Any)

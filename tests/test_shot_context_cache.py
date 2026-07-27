"""Bounds, keying, and invalidation for the league shot-context memo."""

import threading

from app.shot_context import LeagueContextCache

CLAUSE = "sa.season = %s"
FILTERED = "sa.season = %s AND sa.period = %s"


def _key(clause: str, params: tuple, loaded_at: str = "2026-07-22T18:16:21") -> tuple:
    return (clause, params, loaded_at)


def test_a_caller_cannot_grow_the_cache_without_bound() -> None:
    """context_params is caller-controlled, so distinct keys are unlimited."""
    cache = LeagueContextCache(max_entries=16)
    for period in range(500):
        cache.get_or_compute(_key(FILTERED, ("2025-26", period)), lambda: {"fg_pct": 0.47})
    assert cache.tracked_entries == 16


def test_a_full_cache_recomputes_rather_than_answering_from_another_entry() -> None:
    cache = LeagueContextCache(max_entries=2)
    cache.get_or_compute(_key(FILTERED, ("2025-26", 1)), lambda: "period-1")
    cache.get_or_compute(_key(FILTERED, ("2025-26", 2)), lambda: "period-2")
    # Evicts period-1 as least recently used.
    cache.get_or_compute(_key(FILTERED, ("2025-26", 3)), lambda: "period-3")

    recomputed = cache.get_or_compute(_key(FILTERED, ("2025-26", 1)), lambda: "period-1")
    assert recomputed == "period-1"


def test_different_filter_sets_do_not_collide() -> None:
    """A season-only key would serve one filtered baseline in place of another.

    This is the failure mode that returns plausible numbers rather than an error,
    so it is the one worth pinning.
    """
    cache = LeagueContextCache(max_entries=64)
    home = cache.get_or_compute(_key(FILTERED, ("2025-26", 1)), lambda: "first-quarter")
    away = cache.get_or_compute(_key(FILTERED, ("2025-26", 4)), lambda: "fourth-quarter")
    unfiltered = cache.get_or_compute(_key(CLAUSE, ("2025-26",)), lambda: "whole-season")

    assert (home, away, unfiltered) == ("first-quarter", "fourth-quarter", "whole-season")


def test_a_changed_load_retires_cached_values() -> None:
    """Promotion replaces data without restarting the process."""
    cache = LeagueContextCache(max_entries=64)
    before = cache.get_or_compute(_key(CLAUSE, ("2025-26",), "load-one"), lambda: "old-data")
    after = cache.get_or_compute(_key(CLAUSE, ("2025-26",), "load-two"), lambda: "new-data")

    assert before == "old-data"
    assert after == "new-data"


def test_an_unchanged_load_serves_without_recomputing() -> None:
    cache = LeagueContextCache(max_entries=64)
    calls = []

    def compute() -> str:
        calls.append(1)
        return "value"

    cache.get_or_compute(_key(CLAUSE, ("2025-26",)), compute)
    cache.get_or_compute(_key(CLAUSE, ("2025-26",)), compute)

    assert len(calls) == 1


def test_the_cache_is_safe_under_concurrent_access() -> None:
    """Sync handlers run on a threadpool, so this is the normal case."""
    cache = LeagueContextCache(max_entries=32)
    errors: list[BaseException] = []

    def hammer(offset: int) -> None:
        try:
            for index in range(200):
                key = _key(FILTERED, ("2025-26", (offset + index) % 100))
                cache.get_or_compute(key, lambda: {"fg_pct": 0.47})
        except BaseException as exc:  # noqa: BLE001 - surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=hammer, args=(offset,)) for offset in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert cache.tracked_entries <= 32


def test_computation_does_not_hold_the_lock() -> None:
    """A DB query under the lock would serialize every shot-chart request.

    The limiter can hold its lock throughout because its work is trivial. Here the
    computation is a whole-season aggregate, so holding the lock across it would be
    far worse than the repeated work this cache exists to remove.
    """
    cache = LeagueContextCache(max_entries=8)
    entered = threading.Event()
    release = threading.Event()

    def slow_compute() -> str:
        entered.set()
        release.wait(timeout=5)
        return "slow"

    worker = threading.Thread(
        target=lambda: cache.get_or_compute(_key(CLAUSE, ("slow",)), slow_compute)
    )
    worker.start()
    assert entered.wait(timeout=5)

    # While the slow computation is in flight, another key must still resolve.
    done = threading.Event()

    def other() -> None:
        cache.get_or_compute(_key(CLAUSE, ("fast",)), lambda: "fast")
        done.set()

    threading.Thread(target=other).start()
    assert done.wait(timeout=5), "a slow computation blocked an unrelated key"

    release.set()
    worker.join(timeout=5)

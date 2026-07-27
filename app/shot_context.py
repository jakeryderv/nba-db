"""Process-local memo for the league-wide shot context.

The shot chart compares a subject against a league baseline. With no filters
applied that baseline is a whole-season aggregate producing the same league FG%
and the same ~30 zone rows for every caller, recomputed on every request, over a
dataset that changes only when an operator promotes a season.

Two properties are load-bearing rather than defensive:

The cache is bounded because it is keyed partly on filter values a caller
supplies. Without a cap, a caller varying filters grows process memory without
limit on a single replica -- the same hazard the rate limiter is bounded for.

The cache is locked because sync handlers run on a threadpool, so concurrent
shot-chart requests are the normal case and `move_to_end` followed by an insert
and an eviction is not atomic.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

# Ordinary filter combinations fit comfortably; a caller enumerating filters hits
# the cap instead of growing memory. Each entry is a small scalar or a ~30-row map.
DEFAULT_MAX_ENTRIES = 512

# The cache does not interpret its keys. Callers compose them from the rendered
# context predicate, its parameters, and the season's load stamp, plus a
# discriminator for which value is being cached -- so a new filter changes the key
# by construction rather than by someone remembering to update it.
ContextKey = tuple[Any, ...]


def _positive_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


class LeagueContextCache:
    """A bounded, thread-safe memo whose keys carry their own validity."""

    def __init__(self, max_entries: int | None = None) -> None:
        self.max_entries = max_entries or _positive_int(
            "SHOT_CONTEXT_MAX_ENTRIES", DEFAULT_MAX_ENTRIES
        )
        self._entries: OrderedDict[ContextKey, Any] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def tracked_entries(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def get_or_compute(self, key: ContextKey, compute: Callable[[], Any]) -> Any:
        """Return the cached value for a key, computing it on a miss.

        The computation runs outside the lock. It is a whole-season aggregate, and
        holding the lock across it would serialize every shot-chart request --
        strictly worse than the repeated work this cache exists to remove. The
        cost is that a cold miss under concurrency may compute the same value
        twice, which wastes work without producing a wrong answer.
        """
        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
                return self._entries[key]

        value = compute()

        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            # Evict rather than reject. Unlike the limiter, whose cap must never
            # let a request through unlimited, a cache at its cap simply loses an
            # optimization -- so it fails toward doing the work.
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
        return value


league_context_cache = LeagueContextCache()

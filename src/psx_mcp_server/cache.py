"""A tiny in-memory TTL cache.

Keyed by any hashable (the client uses (method, path, frozenset(form))). Uses a
monotonic clock so wall-clock changes never affect expiry. Eviction is lazy on
get plus oldest-first when the entry cap is exceeded — more than enough for the
handful of endpoints this server polls.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from typing import Any


class TTLCache:
    def __init__(self, max_entries: int = 512, clock: Callable[[], float] = time.monotonic) -> None:
        self._max = max_entries
        self._clock = clock
        self._store: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()

    def get(self, key: Hashable) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: Hashable, value: Any, ttl: float) -> None:
        self._store[key] = (self._clock() + ttl, value)
        self._store.move_to_end(key)
        while len(self._store) > self._max:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()

"""Tests for the in-memory TTL cache."""

from __future__ import annotations

from psx_mcp_server.cache import TTLCache


class FakeClock:
    """A controllable monotonic clock for deterministic TTL tests."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_set_then_get_returns_value():
    cache = TTLCache(clock=FakeClock())
    cache.set("k", "v", ttl=30)
    assert cache.get("k") == "v"


def test_get_missing_returns_none():
    assert TTLCache(clock=FakeClock()).get("nope") is None


def test_entry_expires_after_ttl():
    clock = FakeClock()
    cache = TTLCache(clock=clock)
    cache.set("k", "v", ttl=30)
    clock.advance(29)
    assert cache.get("k") == "v"
    clock.advance(2)  # now 31s elapsed
    assert cache.get("k") is None


def test_distinct_keys_are_independent():
    cache = TTLCache(clock=FakeClock())
    cache.set(("GET", "/a"), 1, ttl=30)
    cache.set(("POST", "/a", frozenset({("symbol", "HBL")})), 2, ttl=30)
    assert cache.get(("GET", "/a")) == 1
    assert cache.get(("POST", "/a", frozenset({("symbol", "HBL")}))) == 2


def test_max_entries_evicts_oldest():
    cache = TTLCache(max_entries=2, clock=FakeClock())
    cache.set("a", 1, ttl=100)
    cache.set("b", 2, ttl=100)
    cache.set("c", 3, ttl=100)  # should evict "a"
    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3

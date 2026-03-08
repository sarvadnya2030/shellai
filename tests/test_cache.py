"""Tests for the TTL LRU command cache."""

import time
import json
import pytest
from pathlib import Path
from shellai.cache import CommandCache


@pytest.fixture
def cache(tmp_path) -> CommandCache:
    return CommandCache(tmp_path / "cache.json", max_size=5, ttl_seconds=60)


class TestCacheGetPut:
    def test_miss_on_empty_cache(self, cache):
        assert cache.get("find large files") is None

    def test_put_then_get(self, cache):
        cache.put("list processes", "ps aux", "qwen2.5:3b")
        assert cache.get("list processes") == "ps aux"

    def test_normalises_whitespace(self, cache):
        cache.put("list   processes", "ps aux", "qwen2.5:3b")
        assert cache.get("list processes") == "ps aux"

    def test_case_insensitive_key(self, cache):
        cache.put("List Processes", "ps aux", "qwen2.5:3b")
        assert cache.get("list processes") == "ps aux"

    def test_different_requests_dont_collide(self, cache):
        cache.put("show disk usage", "df -h", "qwen2.5:3b")
        cache.put("show memory", "free -h", "qwen2.5:3b")
        assert cache.get("show disk usage") == "df -h"
        assert cache.get("show memory") == "free -h"


class TestLRUEviction:
    def test_evicts_oldest_when_full(self, cache):
        for i in range(5):
            cache.put(f"request {i}", f"cmd {i}", "model")
        # Cache is full; adding one more should evict request 0
        cache.put("request 5", "cmd 5", "model")
        assert cache.get("request 0") is None
        assert cache.get("request 5") == "cmd 5"

    def test_hit_refreshes_lru_order(self, cache):
        for i in range(5):
            cache.put(f"request {i}", f"cmd {i}", "model")
        # Access request 0 to promote it
        cache.get("request 0")
        # Now add one more; request 1 should be evicted (oldest unaccessed)
        cache.put("request 5", "cmd 5", "model")
        assert cache.get("request 0") == "cmd 0"
        assert cache.get("request 1") is None


class TestTTL:
    def test_expired_entry_returns_none(self, tmp_path):
        c = CommandCache(tmp_path / "cache.json", ttl_seconds=1)
        c.put("show uptime", "uptime", "model")
        time.sleep(1.1)
        assert c.get("show uptime") is None

    def test_fresh_entry_is_returned(self, cache):
        cache.put("show uptime", "uptime", "model")
        assert cache.get("show uptime") == "uptime"


class TestStats:
    def test_hit_rate_zero_on_empty(self, cache):
        assert cache.stats["hit_rate"] == 0.0

    def test_hit_increments_counter(self, cache):
        cache.put("ls", "ls -lah", "model")
        cache.get("ls")
        cache.get("ls")
        assert cache.stats["hits"] == 2

    def test_miss_increments_counter(self, cache):
        cache.get("nonexistent request")
        assert cache.stats["misses"] == 1

    def test_hit_rate_calculation(self, cache):
        cache.put("ls", "ls", "model")
        cache.get("ls")          # hit
        cache.get("missing")     # miss
        assert cache.stats["hit_rate"] == 0.5


class TestPersistence:
    def test_cache_survives_reload(self, tmp_path):
        path = tmp_path / "cache.json"
        c1 = CommandCache(path)
        c1.put("show processes", "ps aux", "model")
        c2 = CommandCache(path)
        assert c2.get("show processes") == "ps aux"

    def test_clear_removes_all_entries(self, cache):
        cache.put("cmd1", "ls", "model")
        cache.put("cmd2", "ps", "model")
        cache.clear()
        assert cache.get("cmd1") is None
        assert cache.stats["size"] == 0

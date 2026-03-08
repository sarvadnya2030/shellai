"""TTL-aware LRU request cache for ShellAI.

Caches (normalised NL request) → shell command mappings so identical or
near-identical requests don't hit the LLM a second time.

Properties
----------
- Thread-safe via a single threading.Lock
- LRU eviction once max_size is reached
- Per-entry TTL: stale entries are discarded on read
- Disk-persisted as JSON so the cache survives across CLI sessions
- O(1) get/put via collections.OrderedDict
"""

import json
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, asdict
from pathlib import Path
from threading import Lock
from typing import Optional


@dataclass
class _Entry:
    command: str
    model: str
    ts: float      # unix timestamp of insertion
    hits: int = 0  # number of cache hits


class CommandCache:
    """Thread-safe, TTL LRU cache backed by a JSON file."""

    def __init__(
        self,
        path: Path,
        max_size: int = 200,
        ttl_seconds: int = 3600,
    ) -> None:
        self.path = path
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._lock = Lock()
        self._store: OrderedDict[str, _Entry] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._load()

    # ── Public API ─────────────────────────────────────────────────────────────

    def get(self, request: str) -> Optional[str]:
        """Return cached command or None (updates LRU order on hit)."""
        key = self._key(request)
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            if time.time() - entry.ts > self.ttl:
                del self._store[key]
                self._misses += 1
                return None
            self._store.move_to_end(key)
            entry.hits += 1
            self._hits += 1
            return entry.command

    def put(self, request: str, command: str, model: str) -> None:
        """Insert or update a cache entry; evicts LRU if at capacity."""
        key = self._key(request)
        with self._lock:
            self._store[key] = _Entry(command=command, model=model, ts=time.time())
            self._store.move_to_end(key)
            if len(self._store) > self.max_size:
                self._store.popitem(last=False)
        self._persist()

    def invalidate(self, request: str) -> None:
        """Remove a specific entry."""
        key = self._key(request)
        with self._lock:
            self._store.pop(key, None)
        self._persist()

    def clear(self) -> None:
        """Evict all entries and reset counters."""
        with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0
        self._persist()

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "size": len(self._store),
            "max_size": self.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total else 0.0,
            "ttl_seconds": self.ttl,
        }

    # ── Internals ──────────────────────────────────────────────────────────────

    @staticmethod
    def _key(request: str) -> str:
        """Normalise and hash a request string to a stable cache key."""
        normalised = " ".join(request.lower().split())
        return hashlib.sha256(normalised.encode()).hexdigest()[:16]

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw: dict = json.loads(self.path.read_text())
            for k, v in raw.items():
                self._store[k] = _Entry(**v)
        except Exception:
            pass  # corrupt cache file — start fresh

    def _persist(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                data = {k: asdict(v) for k, v in self._store.items()}
            self.path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass  # never crash on cache write

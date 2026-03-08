"""Structured telemetry for ShellAI.

Every request (CLI, REPL, API) appends a JSON record to a JSONL file.
The `compute_stats` function derives aggregate insights: latency percentiles,
cache hit rate, model tier distribution, risk breakdown, etc.

Design
------
- Append-only JSONL — no database, no external deps
- Never raises: metric writes are best-effort, never block the happy path
- `ai stats` in the CLI surfaces these aggregates as a human-readable report
"""

import json
import uuid
import time
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import CONFIG_DIR

METRICS_FILE = CONFIG_DIR / "metrics.jsonl"


@dataclass
class RequestMetric:
    request_id: str        # 8-char hex, unique per request
    ts: str                # ISO-8601 UTC
    request: str           # original NL input
    command: str           # generated shell command
    model: str             # ollama model tag used
    tier: str              # "fast" | "strong"
    latency_ms: float      # wall-clock LLM time (0 if cache hit)
    cache_hit: bool
    risk_level: str        # safe | medium | high | critical
    executed: bool
    returncode: Optional[int]
    source: str            # "cli" | "repl" | "api"


def build(
    *,
    request: str,
    command: str,
    model: str,
    tier: str,
    latency_ms: float,
    cache_hit: bool,
    risk_level: str,
    executed: bool,
    returncode: Optional[int],
    source: str = "cli",
) -> RequestMetric:
    return RequestMetric(
        request_id=uuid.uuid4().hex[:8],
        ts=datetime.now(timezone.utc).isoformat(),
        request=request,
        command=command,
        model=model,
        tier=tier,
        latency_ms=round(latency_ms, 1),
        cache_hit=cache_hit,
        risk_level=risk_level,
        executed=executed,
        returncode=returncode,
        source=source,
    )


def record(metric: RequestMetric) -> None:
    """Append metric to JSONL file. Never raises."""
    try:
        METRICS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(METRICS_FILE, "a") as f:
            f.write(json.dumps(asdict(metric)) + "\n")
    except Exception:
        pass


def load_recent(n: int = 1000) -> list[dict]:
    if not METRICS_FILE.exists():
        return []
    try:
        lines = METRICS_FILE.read_text().splitlines()[-n:]
        return [json.loads(line) for line in lines if line.strip()]
    except Exception:
        return []


def compute_stats(n: int = 1000) -> dict:
    """Aggregate the last n records into a stats summary."""
    records = load_recent(n)
    if not records:
        return {}

    latencies = [r["latency_ms"] for r in records if not r.get("cache_hit")]
    cache_hits = sum(1 for r in records if r.get("cache_hit"))
    executed = sum(1 for r in records if r.get("executed"))
    success = sum(1 for r in records if r.get("returncode") == 0)

    sorted_lat = sorted(latencies) if latencies else [0]

    return {
        "total_requests": len(records),
        "cache_hit_rate": round(cache_hits / len(records), 3),
        "execution_rate": round(executed / len(records), 3),
        "success_rate": round(success / executed, 3) if executed else 0.0,
        "llm_calls": len(latencies),
        "avg_latency_ms": round(sum(sorted_lat) / len(sorted_lat), 1),
        "p50_latency_ms": round(sorted_lat[len(sorted_lat) // 2], 1),
        "p95_latency_ms": round(sorted_lat[int(len(sorted_lat) * 0.95)], 1),
        "model_usage": dict(Counter(r["model"] for r in records)),
        "tier_usage": dict(Counter(r.get("tier", "fast") for r in records)),
        "risk_distribution": dict(Counter(r["risk_level"] for r in records)),
        "source_distribution": dict(Counter(r.get("source", "cli") for r in records)),
    }

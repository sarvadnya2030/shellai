"""Intelligent model router for ShellAI.

Routes each request to the appropriate Qwen model tier based on an estimated
complexity score derived from heuristic text analysis.

  Simple / unambiguous → fast model  (qwen2.5:3b  — low latency)
  Complex / multi-step  → strong model (qwen2.5:7b — higher accuracy)

The score is intentionally lightweight (no ML inference) so routing itself
adds zero latency.
"""

import re
from dataclasses import dataclass
from typing import Literal

ModelTier = Literal["fast", "strong"]

# Tokens that suggest a multi-step or structurally complex operation
_COMPLEX_TOKENS = {
    "pipeline", "chain", "multiple", "foreach", "loop", "while",
    "recursive", "nested", "parallel", "stream", "transform",
    "parse", "extract", "aggregate", "monitor", "watch", "continuously",
    "schedule", "cron", "daemon", "background", "encrypt", "decrypt",
    "compress", "sign", "verify", "checksum", "migrate", "backup",
    "restore", "sync", "replicate", "analyse", "analyze", "summarise",
    "summarize", "all files", "every file", "bulk", "batch", "rolling",
    "rotate", "archive", "diff", "merge", "split", "chunk",
}

# Tokens that suggest a simple, read-only or single-step operation
_SIMPLE_TOKENS = {
    "list", "show", "display", "print", "get", "find", "search",
    "check", "count", "size", "running", "processes", "disk",
    "memory", "cpu", "uptime", "who", "whoami", "hostname", "ip",
    "pid", "port", "open", "current", "today", "last", "recent",
}

# Conjunctions that imply chained / multi-step intent
_CONNECTORS = {"then", "after", "before", "finally", "also", "next", "while"}


@dataclass(frozen=True)
class RoutingDecision:
    tier: ModelTier
    model: str
    score: float   # 0.0 = definitely simple, 1.0 = definitely complex
    reason: str


def _score(request: str) -> float:
    """Return a 0.0–1.0 complexity estimate for a natural language request."""
    text = request.lower()
    tokens = set(re.findall(r"\w+", text))
    s = 0.0

    # Length penalty: longer requests tend to be more complex
    words = len(text.split())
    if words > 14:
        s += 0.25
    elif words > 8:
        s += 0.10

    # Complex vocabulary
    s += min(len(tokens & _COMPLEX_TOKENS) * 0.25, 0.50)

    # Simple vocabulary lowers the score
    s -= min(len(tokens & _SIMPLE_TOKENS) * 0.15, 0.30)

    # Connectors imply multi-step intent
    s += min(len(tokens & _CONNECTORS) * 0.12, 0.25)

    # Pipe / redirect intent in the natural language itself
    if any(kw in text for kw in (" | ", "pipe", "redirect", "output to", "into a file")):
        s += 0.20

    # Numeric ranges / loops
    if re.search(r"\b(for|each|every)\b.*\b(file|dir|entry|line|item)\b", text):
        s += 0.20

    return max(0.0, min(1.0, s))


class ModelRouter:
    """Routes requests to the appropriate model based on complexity scoring."""

    THRESHOLD = 0.35  # score >= threshold → strong model

    def __init__(self, fast_model: str, strong_model: str) -> None:
        self.fast_model = fast_model
        self.strong_model = strong_model

    def route(self, request: str) -> RoutingDecision:
        score = _score(request)
        if score >= self.THRESHOLD:
            return RoutingDecision(
                tier="strong",
                model=self.strong_model,
                score=round(score, 3),
                reason=f"complexity {score:.2f} ≥ threshold {self.THRESHOLD}",
            )
        return RoutingDecision(
            tier="fast",
            model=self.fast_model,
            score=round(score, 3),
            reason=f"complexity {score:.2f} < threshold {self.THRESHOLD}",
        )

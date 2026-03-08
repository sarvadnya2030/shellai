"""Intelligent model router for ShellAI.

3-tier routing based on a lightweight complexity score (no ML inference):

  score < 0.15  → tiny   (qwen3.5:0.8b — ultra-fast, trivial queries)
  score < 0.35  → fast   (qwen3.5:2b   — standard queries)
  score >= 0.35 → strong (qwen3.5:4b   — complex / multi-step queries)

Routing itself adds zero latency.
"""

import re
from dataclasses import dataclass
from typing import Literal

ModelTier = Literal["tiny", "fast", "strong"]

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
    """Routes requests across three model tiers based on complexity scoring.

    Tier selection:
      tiny   — short queries (≤ 4 words) with no complex indicators
      fast   — standard queries (complexity score < 0.35)
      strong — complex / multi-step queries (complexity score ≥ 0.35)
    """

    TINY_MAX_WORDS = 4      # requests this short go to tiny (if score == 0)
    FAST_THRESHOLD = 0.35   # score < this → fast, else → strong

    def __init__(self, tiny_model: str, fast_model: str, strong_model: str) -> None:
        self.tiny_model = tiny_model
        self.fast_model = fast_model
        self.strong_model = strong_model

    def route(self, request: str) -> RoutingDecision:
        score = _score(request)
        word_count = len(request.split())

        # Short, unambiguous queries → tiny
        if score == 0.0 and word_count <= self.TINY_MAX_WORDS:
            return RoutingDecision(
                tier="tiny",
                model=self.tiny_model,
                score=0.0,
                reason=f"trivial: {word_count} words, score=0",
            )
        if score < self.FAST_THRESHOLD:
            return RoutingDecision(
                tier="fast",
                model=self.fast_model,
                score=round(score, 3),
                reason=f"complexity {score:.2f} < {self.FAST_THRESHOLD}",
            )
        return RoutingDecision(
            tier="strong",
            model=self.strong_model,
            score=round(score, 3),
            reason=f"complexity {score:.2f} ≥ {self.FAST_THRESHOLD}",
        )

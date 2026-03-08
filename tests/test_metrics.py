"""Tests for structured telemetry."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from shellai.metrics import build, record, load_recent, compute_stats, RequestMetric


def _make_metric(**overrides) -> RequestMetric:
    defaults = dict(
        request="show processes",
        command="ps aux",
        model="qwen2.5:3b",
        tier="fast",
        latency_ms=312.5,
        cache_hit=False,
        risk_level="safe",
        executed=True,
        returncode=0,
        source="cli",
    )
    defaults.update(overrides)
    return build(**defaults)


class TestBuild:
    def test_has_request_id(self):
        m = _make_metric()
        assert len(m.request_id) == 8

    def test_has_iso_timestamp(self):
        m = _make_metric()
        assert "T" in m.ts and "+" in m.ts or "Z" in m.ts or m.ts.endswith("+00:00")

    def test_latency_rounded(self):
        m = _make_metric(latency_ms=1234.5678)
        assert m.latency_ms == 1234.6

    def test_fields_match_input(self):
        m = _make_metric(command="ls -lah", tier="strong", cache_hit=True)
        assert m.command == "ls -lah"
        assert m.tier == "strong"
        assert m.cache_hit is True


class TestRecordAndLoad:
    def test_record_appends_to_file(self, tmp_path):
        metrics_path = tmp_path / "metrics.jsonl"
        with patch("shellai.metrics.METRICS_FILE", metrics_path):
            record(_make_metric())
            record(_make_metric())
        lines = metrics_path.read_text().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["command"] == "ps aux"

    def test_load_returns_records(self, tmp_path):
        metrics_path = tmp_path / "metrics.jsonl"
        with patch("shellai.metrics.METRICS_FILE", metrics_path):
            record(_make_metric(command="df -h"))
            loaded = load_recent(10)
        assert len(loaded) == 1
        assert loaded[0]["command"] == "df -h"

    def test_load_respects_n_limit(self, tmp_path):
        metrics_path = tmp_path / "metrics.jsonl"
        with patch("shellai.metrics.METRICS_FILE", metrics_path):
            for _ in range(10):
                record(_make_metric())
            loaded = load_recent(3)
        assert len(loaded) == 3

    def test_load_returns_empty_when_no_file(self, tmp_path):
        with patch("shellai.metrics.METRICS_FILE", tmp_path / "nope.jsonl"):
            assert load_recent() == []


class TestComputeStats:
    def test_returns_empty_dict_on_no_data(self, tmp_path):
        with patch("shellai.metrics.METRICS_FILE", tmp_path / "nope.jsonl"):
            assert compute_stats() == {}

    def test_cache_hit_rate(self, tmp_path):
        metrics_path = tmp_path / "metrics.jsonl"
        with patch("shellai.metrics.METRICS_FILE", metrics_path):
            record(_make_metric(cache_hit=True))
            record(_make_metric(cache_hit=False))
            stats = compute_stats()
        assert stats["cache_hit_rate"] == 0.5

    def test_success_rate(self, tmp_path):
        metrics_path = tmp_path / "metrics.jsonl"
        with patch("shellai.metrics.METRICS_FILE", metrics_path):
            record(_make_metric(executed=True, returncode=0))
            record(_make_metric(executed=True, returncode=1))
            stats = compute_stats()
        assert stats["success_rate"] == 0.5

    def test_model_usage_counted(self, tmp_path):
        metrics_path = tmp_path / "metrics.jsonl"
        with patch("shellai.metrics.METRICS_FILE", metrics_path):
            record(_make_metric(model="qwen2.5:3b"))
            record(_make_metric(model="qwen2.5:3b"))
            record(_make_metric(model="qwen2.5:7b"))
            stats = compute_stats()
        assert stats["model_usage"]["qwen2.5:3b"] == 2
        assert stats["model_usage"]["qwen2.5:7b"] == 1

    def test_latency_stats_exclude_cache_hits(self, tmp_path):
        metrics_path = tmp_path / "metrics.jsonl"
        with patch("shellai.metrics.METRICS_FILE", metrics_path):
            record(_make_metric(cache_hit=False, latency_ms=100))
            record(_make_metric(cache_hit=False, latency_ms=200))
            record(_make_metric(cache_hit=True, latency_ms=0))
            stats = compute_stats()
        assert stats["llm_calls"] == 2
        assert stats["avg_latency_ms"] == 150.0

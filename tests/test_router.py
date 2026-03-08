"""Tests for the model complexity router."""

import pytest
from shellai.router import ModelRouter, _score


FAST = "qwen2.5:3b"
STRONG = "qwen2.5:4b"


@pytest.fixture
def router() -> ModelRouter:
    return ModelRouter(fast_model=FAST, strong_model=STRONG)


class TestComplexityScore:
    def test_simple_list_request_is_low(self):
        assert _score("list running processes") < 0.35

    def test_show_disk_usage_is_low(self):
        assert _score("show disk usage") < 0.35

    def test_find_file_is_low(self):
        assert _score("find files larger than 1GB") < 0.35

    def test_complex_pipeline_is_high(self):
        assert _score("monitor cpu usage and pipe output to a log file continuously") >= 0.35

    def test_multi_step_connectors_raise_score(self):
        assert _score("compress all files then encrypt them and backup to /tmp") >= 0.35

    def test_loop_intent_raises_score(self):
        assert _score("for each file in the directory compress and rename it to lowercase") >= 0.35

    def test_score_bounded_0_to_1(self):
        for req in ["ls", "x" * 300, "find backup sync encrypt migrate parallel recursive"]:
            s = _score(req)
            assert 0.0 <= s <= 1.0, f"score out of bounds for {req!r}: {s}"


class TestModelRouting:
    def test_simple_request_routes_to_fast(self, router):
        decision = router.route("show running processes")
        assert decision.tier == "fast"
        assert decision.model == FAST

    def test_complex_request_routes_to_strong(self, router):
        decision = router.route("recursively compress and archive all log files then sync to backup")
        assert decision.tier == "strong"
        assert decision.model == STRONG

    def test_decision_contains_score_and_reason(self, router):
        decision = router.route("list files")
        assert 0.0 <= decision.score <= 1.0
        assert len(decision.reason) > 0

    def test_empty_request_routes_to_fast(self, router):
        decision = router.route("")
        assert decision.tier == "fast"

    def test_routing_is_deterministic(self, router):
        req = "find all python files and count lines"
        assert router.route(req).tier == router.route(req).tier

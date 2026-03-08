"""Integration tests for the REST API server.

Spins up a real ThreadingHTTPServer on a random port and tests each endpoint
using only stdlib http.client — no external test-client deps.
"""

import http.client
import json
import threading
import time
import pytest
from unittest.mock import MagicMock, patch

from shellai.config import Config
from shellai.server import ShellAIServer, _Handler
from shellai.cache import CommandCache
from shellai.router import ModelRouter


# ── Test fixture ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def server_port(tmp_path_factory):
    """Start a ShellAI server on a random free port; yield port; stop."""
    import socket

    config = Config()
    tmp = tmp_path_factory.mktemp("server")

    # Inject a mock Ollama client that returns canned responses
    mock_client = MagicMock()
    mock_client.is_available.return_value = True
    mock_client.list_models.return_value = ["qwen2.5:3b", "qwen2.5:7b"]
    mock_client.generate.return_value = "ps aux"

    router = ModelRouter("qwen2.5:3b", "qwen2.5:7b")
    cache = CommandCache(tmp / "cache.json")

    _Handler._config = config
    _Handler._client = mock_client
    _Handler._router = router
    _Handler._cache = cache

    # Find a free port
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    from shellai.server import _ThreadingHTTPServer
    httpd = _ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    time.sleep(0.1)  # give server time to start

    yield port

    httpd.shutdown()


def _get(port: int, path: str) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path)
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read())


def _post(port: int, path: str, body: dict) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    data = json.dumps(body).encode()
    conn.request("POST", path, body=data, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read())


def _delete(port: int, path: str) -> tuple[int, dict]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("DELETE", path)
    resp = conn.getresponse()
    return resp.status, json.loads(resp.read())


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_returns_200(self, server_port):
        status, body = _get(server_port, "/api/health")
        assert status == 200

    def test_ollama_reachable_true(self, server_port):
        _, body = _get(server_port, "/api/health")
        assert body["ollama_reachable"] is True

    def test_contains_model_info(self, server_port):
        _, body = _get(server_port, "/api/health")
        assert "model_fast" in body
        assert "model_strong" in body

    def test_contains_cache_stats(self, server_port):
        _, body = _get(server_port, "/api/health")
        assert "cache" in body
        assert "hit_rate" in body["cache"]


class TestModelsEndpoint:
    def test_returns_list(self, server_port):
        status, body = _get(server_port, "/api/models")
        assert status == 200
        assert isinstance(body["models"], list)


class TestGenerateEndpoint:
    def test_generates_command(self, server_port):
        status, body = _post(server_port, "/api/generate", {"request": "show processes"})
        assert status == 200
        assert body["command"] == "ps aux"

    def test_returns_risk_level(self, server_port):
        _, body = _post(server_port, "/api/generate", {"request": "show processes"})
        assert body["risk_level"] in ("safe", "medium", "high", "critical")

    def test_second_call_is_cache_hit(self, server_port):
        _post(server_port, "/api/generate", {"request": "unique cache test request xyz"})
        _, body = _post(server_port, "/api/generate", {"request": "unique cache test request xyz"})
        assert body["cache_hit"] is True

    def test_missing_request_field_returns_400(self, server_port):
        status, body = _post(server_port, "/api/generate", {})
        assert status == 400
        assert "error" in body

    def test_invalid_json_returns_400(self, server_port):
        conn = http.client.HTTPConnection("127.0.0.1", server_port, timeout=5)
        conn.request("POST", "/api/generate", body=b"not json",
                     headers={"Content-Type": "application/json", "Content-Length": "8"})
        resp = conn.getresponse()
        assert resp.status == 400


class TestExplainEndpoint:
    def test_returns_explanation(self, server_port):
        status, body = _post(server_port, "/api/explain", {"command": "ls -lah"})
        assert status == 200
        assert "explanation" in body
        assert "latency_ms" in body

    def test_missing_command_returns_400(self, server_port):
        status, _ = _post(server_port, "/api/explain", {})
        assert status == 400


class TestCacheEndpoints:
    def test_cache_stats_endpoint(self, server_port):
        status, body = _get(server_port, "/api/cache/stats")
        assert status == 200
        assert "hit_rate" in body

    def test_delete_cache_clears_it(self, server_port):
        _post(server_port, "/api/generate", {"request": "delete cache test abc"})
        status, body = _delete(server_port, "/api/cache")
        assert status == 200
        assert body["ok"] is True


class TestNotFound:
    def test_unknown_get_returns_404(self, server_port):
        status, _ = _get(server_port, "/api/nonexistent")
        assert status == 404

    def test_unknown_post_returns_404(self, server_port):
        status, _ = _post(server_port, "/api/nonexistent", {})
        assert status == 404

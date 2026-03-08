"""Local REST API server for ShellAI.

Exposes ShellAI as a JSON HTTP service so IDE extensions, scripts, and
other tools can consume it programmatically — zero extra dependencies,
built entirely on Python's stdlib http.server + socketserver.

Usage
-----
    ai serve [--host 127.0.0.1] [--port 8765]

Endpoints
---------
    POST /api/generate      NL request → shell command + safety rating
    POST /api/explain       shell command → plain-English explanation
    GET  /api/health        Ollama connectivity + active model info
    GET  /api/models        list available Ollama models
    GET  /api/history       recent command history  (?n=20)
    GET  /api/stats         aggregate telemetry stats
    GET  /api/cache/stats   cache hit rate + size
    DELETE /api/cache       flush the command cache

Concurrency
-----------
ThreadingMixIn gives each request its own thread — adequate for the
local-tool use-case without adding asyncio complexity.
"""

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Any
from urllib.parse import parse_qs, urlparse

from .cache import CommandCache
from .config import CONFIG_DIR, Config
from .history import load_history
from .metrics import build as build_metric
from .metrics import compute_stats, record
from .ollama_client import OllamaClient
from .prompts import COMMAND_GENERATION_PROMPT, EXPLAIN_PROMPT
from .router import ModelRouter
from .safety import check_safety
from .utils import clean_llm_command


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle each HTTP request in a dedicated thread."""

    daemon_threads = True


class _Handler(BaseHTTPRequestHandler):
    """Route HTTP requests to the appropriate ShellAI handler."""

    # Class-level deps injected by ShellAIServer.serve() before listen
    _config: Config
    _client: OllamaClient
    _router: ModelRouter
    _cache: CommandCache

    # ── Silence default Apache-style access log ─────────────────────────────

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: D102
        pass

    # ── HTTP method dispatch ────────────────────────────────────────────────

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        match parsed.path:
            case "/api/health":
                self._health()
            case "/api/models":
                self._models()
            case "/api/history":
                self._history(int(qs.get("n", ["20"])[0]))
            case "/api/stats":
                self._stats()
            case "/api/cache/stats":
                self._cache_stats()
            case _:
                self._json({"error": "Not found"}, 404)

    def do_DELETE(self) -> None:  # noqa: N802
        if self.path == "/api/cache":
            self._cache.clear()
            self._json({"ok": True, "message": "Cache cleared"})
        else:
            self._json({"error": "Not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        body = self._read_json_body()
        if body is None:
            return
        match self.path:
            case "/api/generate":
                self._generate(body)
            case "/api/explain":
                self._explain(body)
            case _:
                self._json({"error": "Not found"}, 404)

    # ── Endpoint handlers ───────────────────────────────────────────────────

    def _generate(self, body: dict) -> None:
        request = body.get("request", "").strip()
        if not request:
            self._json({"error": "'request' field is required"}, 400)
            return

        # Cache lookup — skip LLM entirely on hit
        cached_cmd = self._cache.get(request)
        if cached_cmd:
            safety = check_safety(cached_cmd)
            self._json({
                "command": cached_cmd,
                "risk_level": safety.risk_level,
                "safe": safety.safe,
                "reason": safety.reason,
                "cache_hit": True,
                "model": None,
                "tier": None,
                "latency_ms": 0,
            })
            return

        decision = self._router.route(request)
        self._client.model = decision.model

        t0 = time.monotonic()
        raw = self._client.generate(COMMAND_GENERATION_PROMPT.format(request=request))
        latency_ms = (time.monotonic() - t0) * 1000

        command = clean_llm_command(raw)
        if not command:
            self._json({"error": "Model returned an unparseable response"}, 422)
            return

        safety = check_safety(command)
        self._cache.put(request, command, decision.model)

        record(build_metric(
            request=request,
            command=command,
            model=decision.model,
            tier=decision.tier,
            latency_ms=latency_ms,
            cache_hit=False,
            risk_level=safety.risk_level,
            executed=False,
            returncode=None,
            source="api",
        ))

        self._json({
            "command": command,
            "risk_level": safety.risk_level,
            "safe": safety.safe,
            "reason": safety.reason,
            "cache_hit": False,
            "model": decision.model,
            "tier": decision.tier,
            "routing_score": decision.score,
            "latency_ms": round(latency_ms, 1),
        })

    def _explain(self, body: dict) -> None:
        command = body.get("command", "").strip()
        if not command:
            self._json({"error": "'command' field is required"}, 400)
            return
        t0 = time.monotonic()
        explanation = self._client.generate(EXPLAIN_PROMPT.format(command=command))
        self._json({
            "command": command,
            "explanation": explanation,
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
        })

    def _health(self) -> None:
        available = self._client.is_available()
        models = self._client.list_models() if available else []
        self._json(
            {
                "status": "ok" if available else "degraded",
                "ollama_reachable": available,
                "ollama_url": self._config.ollama_url,
                "model_tiny": self._config.model_tiny,
                "model_fast": self._config.model_fast,
                "model_strong": self._config.model_strong,
                "available_models": models,
                "cache": self._cache.stats,
            },
            status=200 if available else 503,
        )

    def _models(self) -> None:
        self._json({"models": self._client.list_models()})

    def _history(self, n: int) -> None:
        self._json({"entries": load_history(min(n, 100))})

    def _stats(self) -> None:
        self._json(compute_stats())

    def _cache_stats(self) -> None:
        self._json(self._cache.stats)

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _read_json_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, ValueError):
            self._json({"error": "Invalid JSON body"}, 400)
            return None

    def _json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ShellAIServer:
    """Configures and starts the threaded HTTP API server."""

    def __init__(self, config: Config, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.config = config
        self.host = host
        self.port = port

    def serve(self) -> None:
        client = OllamaClient(self.config)
        router = ModelRouter(self.config.model_tiny, self.config.model_fast, self.config.model_strong)
        cache = CommandCache(CONFIG_DIR / "cache.json", ttl_seconds=self.config.cache_ttl)

        # Inject dependencies at the class level (required by BaseHTTPRequestHandler)
        _Handler._config = self.config
        _Handler._client = client
        _Handler._router = router
        _Handler._cache = cache

        server = _ThreadingHTTPServer((self.host, self.port), _Handler)
        addr = f"http://{self.host}:{self.port}"
        print(f"\033[92m✔  ShellAI API  →  {addr}\033[0m")
        print(f"\033[90m   POST /api/generate   POST /api/explain")
        print(f"   GET  /api/health     GET  /api/stats")
        print(f"   GET  /api/cache/stats   DELETE /api/cache")
        print(f"\n   Press Ctrl+C to stop\033[0m\n")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            server.server_close()
            print("\n\033[93m⚡ Server stopped.\033[0m")

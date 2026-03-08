"""Configuration management for ShellAI."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "shellai"
CONFIG_FILE = CONFIG_DIR / "config.json"
HISTORY_FILE = CONFIG_DIR / "history.jsonl"
LOG_FILE = CONFIG_DIR / "shellai.log"

DEFAULTS: dict = {
    # Ollama
    "ollama_url": "http://localhost:11434",
    # Model tiers — routed automatically by complexity score
    "model_fast": "qwen3.5:2b",     # low-latency, simple requests
    "model_strong": "qwen3.5:4b",   # higher accuracy, complex requests
    # Legacy single-model field kept for --model flag compatibility
    "model": "qwen3.5:2b",
    # Timeouts & retries
    "timeout": 120,
    "max_retries": 2,
    # History
    "history_limit": 500,
    # Cache
    "cache_enabled": True,
    "cache_ttl": 3600,              # seconds before a cache entry expires
    # UX
    "stream_explain": True,
    "confirm_safe": True,
    "auto_copy": False,
    "theme": "dark",
    # API server
    "server_host": "127.0.0.1",
    "server_port": 8765,
}


@dataclass
class Config:
    ollama_url: str = DEFAULTS["ollama_url"]
    model_fast: str = DEFAULTS["model_fast"]
    model_strong: str = DEFAULTS["model_strong"]
    model: str = DEFAULTS["model"]           # overridden by --model flag
    timeout: int = DEFAULTS["timeout"]
    max_retries: int = DEFAULTS["max_retries"]
    history_limit: int = DEFAULTS["history_limit"]
    cache_enabled: bool = DEFAULTS["cache_enabled"]
    cache_ttl: int = DEFAULTS["cache_ttl"]
    stream_explain: bool = DEFAULTS["stream_explain"]
    confirm_safe: bool = DEFAULTS["confirm_safe"]
    auto_copy: bool = DEFAULTS["auto_copy"]
    theme: str = DEFAULTS["theme"]
    server_host: str = DEFAULTS["server_host"]
    server_port: int = DEFAULTS["server_port"]

    @classmethod
    def load(cls) -> "Config":
        """Load from disk, falling back to defaults for missing keys."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    data = json.load(f)
                known = {k: data[k] for k in DEFAULTS if k in data}
                return cls(**known)
            except (json.JSONDecodeError, TypeError):
                pass
        return cls()

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(asdict(self), f, indent=2)

    @classmethod
    def init_dirs(cls) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def get_config_path() -> Path:
    return CONFIG_FILE

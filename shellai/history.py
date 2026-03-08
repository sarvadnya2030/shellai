"""Command history logging for ShellAI."""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import HISTORY_FILE, Config


def log_entry(
    request: str,
    command: str,
    executed: bool,
    returncode: Optional[int],
    config: Config,
) -> None:
    """Append an entry to the JSONL history file."""
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.utcnow().isoformat(),
            "request": request,
            "command": command,
            "executed": executed,
            "returncode": returncode,
            "model": config.model,
        }
        with open(HISTORY_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")

        # Trim to history_limit
        _trim_history(config.history_limit)
    except Exception:
        pass  # Never crash on history write


def _trim_history(limit: int) -> None:
    """Keep only the last `limit` entries."""
    if not HISTORY_FILE.exists():
        return
    try:
        lines = HISTORY_FILE.read_text().splitlines()
        if len(lines) > limit:
            HISTORY_FILE.write_text("\n".join(lines[-limit:]) + "\n")
    except Exception:
        pass


def load_history(n: int = 20) -> list[dict]:
    """Return the last n history entries."""
    if not HISTORY_FILE.exists():
        return []
    try:
        lines = HISTORY_FILE.read_text().splitlines()
        entries = []
        for line in reversed(lines):
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            if len(entries) >= n:
                break
        return list(reversed(entries))
    except Exception:
        return []


def clear_history() -> None:
    """Delete all history."""
    if HISTORY_FILE.exists():
        HISTORY_FILE.unlink()

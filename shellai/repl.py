"""Interactive REPL mode for ShellAI  (`ai shell`).

Maintains a sliding window of (request, command) context across multiple
turns so follow-up requests like "make it recursive" or "add -v flag" resolve
correctly — the context is injected into the LLM prompt automatically.

Features
--------
- Session history (! commands: !help, !last, !explain, !history, !clear, !model)
- readline integration for up-arrow recall within the session
- Model routing + cache on every request (same as CLI)
- Per-request telemetry recording
"""

import sys
import time
from typing import Optional

from .cache import CommandCache
from .config import CONFIG_DIR, Config
from .display import (
    C,
    print_blocked,
    print_command_box,
    print_error,
    print_info,
    print_risk_warning,
)
from .executor import stream_command
from .history import log_entry
from .metrics import build as build_metric
from .metrics import record
from .ollama_client import OllamaClient
from .prompts import COMMAND_GENERATION_PROMPT, EXPLAIN_PROMPT
from .router import ModelRouter
from .safety import check_safety
from .utils import clean_llm_command

_CONTEXT_WINDOW = 4   # last N (request, command) pairs injected into prompt

_HELP = f"""
{C.CYAN}{C.BOLD}ShellAI REPL — meta commands:{C.RESET}

  {C.WHITE}!help{C.RESET}        Show this message
  {C.WHITE}!last{C.RESET}        Repeat the last request
  {C.WHITE}!explain{C.RESET}     Explain the last generated command
  {C.WHITE}!history{C.RESET}     Print this session's request/command pairs
  {C.WHITE}!clear{C.RESET}       Wipe session context (start fresh)
  {C.WHITE}!model{C.RESET}       Show active model tiers
  {C.WHITE}!exit{C.RESET}        Exit  (also Ctrl+C / Ctrl+D)

  {C.DIM}Anything else is treated as a natural language request.{C.RESET}
"""


def _build_context_prompt(request: str, session: list[tuple[str, str]]) -> str:
    """Build a prompt that injects the recent session context window."""
    if not session:
        return COMMAND_GENERATION_PROMPT.format(request=request)

    history_block = "\n".join(
        f"  request: {req}\n  command: {cmd}"
        for req, cmd in session[-_CONTEXT_WINDOW:]
    )
    return (
        "You are a Linux shell expert. "
        "Here are the most recent commands in this session:\n"
        f"{history_block}\n\n"
        "Now produce a single shell command for the new request below.\n"
        "Rules: output ONLY the command — no explanation, no markdown.\n\n"
        f"User request: {request}\n\nShell command:"
    )


class ShellAIRepl:
    """Stateful interactive REPL with session context and multi-turn refinement."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = OllamaClient(config)
        self.router = ModelRouter(config.model_tiny, config.model_fast, config.model_strong)
        self.cache = CommandCache(CONFIG_DIR / "cache.json", ttl_seconds=config.cache_ttl)
        self._session: list[tuple[str, str]] = []   # (request, command)
        self._last_request: Optional[str] = None
        self._last_command: Optional[str] = None

    # ── Public entry point ──────────────────────────────────────────────────

    def run(self) -> None:
        print(
            f"\n{C.CYAN}{C.BOLD}ShellAI Shell{C.RESET}  "
            f"{C.DIM}(type !help for commands, Ctrl+C / Ctrl+D to exit){C.RESET}\n"
        )
        self._init_readline()
        while True:
            try:
                line = input(f"{C.GREEN}ai>{C.RESET} ").strip()
            except (EOFError, KeyboardInterrupt):
                print(f"\n{C.DIM}Goodbye.{C.RESET}")
                break
            if not line:
                continue
            if line.startswith("!"):
                self._meta(line)
            else:
                self._handle(line)

    # ── Meta-command dispatch ───────────────────────────────────────────────

    def _meta(self, cmd: str) -> None:
        match cmd:
            case "!exit" | "!quit":
                print(f"{C.DIM}Goodbye.{C.RESET}")
                sys.exit(0)
            case "!help":
                print(_HELP)
            case "!last":
                if self._last_request:
                    self._handle(self._last_request)
                else:
                    print_info("No previous request.")
            case "!explain":
                if self._last_command:
                    expl = self.client.generate(
                        EXPLAIN_PROMPT.format(command=self._last_command)
                    )
                    print(f"\n{C.MAGENTA}{expl}{C.RESET}\n")
                else:
                    print_info("No command to explain yet.")
            case "!history":
                self._print_session()
            case "!clear":
                self._session.clear()
                self._last_request = self._last_command = None
                print_info("Session context cleared.")
            case "!model":
                print_info(
                    f"fast={self.config.model_fast}  "
                    f"strong={self.config.model_strong}"
                )
            case _:
                print_error(f"Unknown command: {cmd}  (try !help)")

    # ── Request handler ─────────────────────────────────────────────────────

    def _handle(self, request: str) -> None:
        # Cache check
        cached = self.cache.get(request)
        cache_hit = cached is not None

        decision = self.router.route(request)
        self.client.model = decision.model

        t0 = time.monotonic()
        if cache_hit:
            command = cached
        else:
            prompt = _build_context_prompt(request, self._session)
            raw = self.client.generate(prompt)
            command = clean_llm_command(raw)
            if command:
                self.cache.put(request, command, decision.model)
        latency_ms = (time.monotonic() - t0) * 1000

        if not command:
            print_error("Could not generate a valid command.")
            return

        safety = check_safety(command)
        if not safety.safe:
            print_blocked(safety.reason or "Dangerous command")
            return

        # Display with routing metadata
        meta_tag = (
            f"{C.DIM}[{decision.tier} · {decision.model} · "
            + ("cache" if cache_hit else f"{latency_ms:.0f}ms")
            + f"]{C.RESET}"
        )
        print(f"\n{meta_tag}")
        print_command_box(command, safety.risk_level)

        if safety.risk_level in ("medium", "high"):
            print_risk_warning(safety.reason or "Risky operation", safety.risk_level)
            print()

        try:
            answer = input(f"{C.BOLD}Execute? [y/N] {C.RESET}").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        executed = answer in ("y", "yes")
        returncode: Optional[int] = None
        if executed:
            print()
            returncode = stream_command(command, timeout=self.config.timeout)
            print()

        # Persist state
        self._last_request = request
        self._last_command = command
        self._session.append((request, command))
        if len(self._session) > _CONTEXT_WINDOW * 2:
            self._session.pop(0)

        log_entry(request, command, executed=executed, returncode=returncode, config=self.config)
        record(build_metric(
            request=request,
            command=command,
            model=decision.model,
            tier=decision.tier,
            latency_ms=latency_ms,
            cache_hit=cache_hit,
            risk_level=safety.risk_level,
            executed=executed,
            returncode=returncode,
            source="repl",
        ))

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _print_session(self) -> None:
        if not self._session:
            print_info("No session history yet.")
            return
        print(f"\n{C.CYAN}{C.BOLD}Session history:{C.RESET}\n")
        for i, (req, cmd) in enumerate(self._session, 1):
            print(f"  {C.DIM}{i}.{C.RESET} {C.WHITE}{req}{C.RESET}")
            print(f"     {C.DIM}{cmd}{C.RESET}")
        print()

    @staticmethod
    def _init_readline() -> None:
        try:
            import readline  # noqa: PLC0415
            readline.set_history_length(500)
        except ImportError:
            pass

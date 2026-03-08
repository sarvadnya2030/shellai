"""
shellai — Natural language Linux terminal assistant powered by Ollama.

Usage:
  ai <request>                    Translate request to shell command
  ai shell                        Interactive REPL with session context
  ai serve [--port N]             Start the local REST API server
  ai stats                        Show telemetry stats
  ai cache [--clear]              Show / clear the command cache
  ai --explain <command>          Explain what a command does
  ai --history                    Show recent command history
  ai --models                     List available Ollama models
  ai --model <name>               Switch model for this session
  ai --config                     Show current configuration
  ai --set <key> <value>          Persist a configuration value
  ai --clear-history              Delete command history
  ai --version                    Show version
"""

import sys
import textwrap
import time
import argparse
from typing import Optional

from . import __version__
from .cache import CommandCache
from .config import CONFIG_DIR, Config
from .display import (
    C, Spinner, banner,
    print_blocked, print_command_box, print_error,
    print_info, print_risk_warning, print_step, print_success, print_warning,
)
from .executor import stream_command
from .history import clear_history, load_history, log_entry
from .metrics import build as build_metric
from .metrics import compute_stats, record
from .ollama_client import OllamaClient
from .prompts import COMMAND_GENERATION_PROMPT, EXPLAIN_PROMPT
from .router import ModelRouter
from .safety import check_safety
from .utils import clean_llm_command, looks_like_command


# ── Core generate flow ────────────────────────────────────────────────────────

def cmd_generate(request: str, client: OllamaClient, config: Config, args) -> None:
    """NL → model router → safety check → confirm → execute."""
    router = ModelRouter(config.model_tiny, config.model_fast, config.model_strong)
    cache = CommandCache(CONFIG_DIR / "cache.json", ttl_seconds=config.cache_ttl)

    print_step(f"Request: {C.WHITE}{request}{C.RESET}")

    # Cache lookup
    cached = cache.get(request) if config.cache_enabled else None
    cache_hit = cached is not None

    if cache_hit:
        command = cached
        decision_tier = "fast"
        decision_model = config.model_fast
        latency_ms = 0.0
        print_info("cache hit")
    else:
        decision = router.route(request)
        client.model = decision.model
        decision_tier = decision.tier
        decision_model = decision.model

        print_info(
            f"routing to {C.WHITE}{decision.tier}{C.RESET} model "
            f"({decision.model})  score={decision.score:.2f}"
        )

        prompt = COMMAND_GENERATION_PROMPT.format(request=request)
        t0 = time.monotonic()
        with Spinner("Generating"):
            raw = client.generate(prompt)
        latency_ms = (time.monotonic() - t0) * 1000
        command = clean_llm_command(raw)

        # Retry once with a stricter prompt on bad output
        if (not command or not looks_like_command(command)) and config.max_retries > 0:
            with Spinner("Retrying"):
                raw = client.generate(
                    prompt + "\n\nRemember: output ONLY the shell command, nothing else."
                )
            command = clean_llm_command(raw)

        if command and config.cache_enabled:
            cache.put(request, command, decision.model)

    if not command:
        print_error("Could not generate a valid command. Try rephrasing.")
        sys.exit(1)

    safety = check_safety(command)

    if not safety.safe:
        print_blocked(safety.reason or "Dangerous command")
        log_entry(request, command, executed=False, returncode=None, config=config)
        sys.exit(2)

    print(f"\n{C.CYAN}Suggested command:{C.RESET}")
    print_command_box(command, safety.risk_level)

    if safety.risk_level in ("medium", "high"):
        print_risk_warning(safety.reason or "Potentially risky", safety.risk_level)
        print()

    if args.explain or safety.risk_level in ("medium", "high"):
        print_step("Explaining command...")
        _print_explanation(command, client, stream=config.stream_explain)
        print()

    if not _confirm("Execute?", default="n"):
        print_info("Cancelled.")
        log_entry(request, command, executed=False, returncode=None, config=config)
        return

    print()
    returncode = stream_command(command, timeout=config.timeout)
    print()

    if returncode == 0:
        print_success("Done  (exit 0)")
    else:
        print_error(f"Command exited with code {returncode}")

    log_entry(request, command, executed=True, returncode=returncode, config=config)
    record(build_metric(
        request=request,
        command=command,
        model=decision_model,
        tier=decision_tier,
        latency_ms=latency_ms,
        cache_hit=cache_hit,
        risk_level=safety.risk_level,
        executed=True,
        returncode=returncode,
        source="cli",
    ))


# ── Sub-command handlers ──────────────────────────────────────────────────────

def _print_explanation(command: str, client: OllamaClient, stream: bool = True) -> None:
    prompt = EXPLAIN_PROMPT.format(command=command)
    print(f"\n{C.MAGENTA}{'─' * 50}{C.RESET}")
    if stream:
        client.generate(prompt, stream=True)
    else:
        print(client.generate(prompt))
    print(f"{C.MAGENTA}{'─' * 50}{C.RESET}")


def cmd_explain(command_parts: list[str], client: OllamaClient, config: Config) -> None:
    command = " ".join(command_parts)
    print_step(f"Explaining: {C.WHITE}{command}{C.RESET}")
    _print_explanation(command, client, stream=config.stream_explain)


def cmd_history(n: int = 20) -> None:
    entries = load_history(n)
    if not entries:
        print_info("No history yet.")
        return
    print(f"\n{C.CYAN}{C.BOLD}Recent history ({len(entries)} entries):{C.RESET}\n")
    for i, e in enumerate(entries, 1):
        ts = e.get("ts", "")[:16].replace("T", " ")
        req = e.get("request", "")
        cmd = e.get("command", "")
        executed = e.get("executed", False)
        rc = e.get("returncode")
        status = (
            f"{C.GREEN}✔{C.RESET}" if (executed and rc == 0)
            else f"{C.RED}✗{C.RESET}" if executed
            else f"{C.GRAY}○{C.RESET}"
        )
        print(f"  {C.DIM}{i:>3}.{C.RESET} {status}  {C.GRAY}{ts}{C.RESET}  {C.CYAN}{req[:40]:<40}{C.RESET}")
        print(f"       {C.DIM}{cmd}{C.RESET}")
    print()


def cmd_models(client: OllamaClient, config: Config) -> None:
    models = client.list_models()
    if not models:
        print_warning("No models found (or Ollama is not running).")
        return
    print(f"\n{C.CYAN}{C.BOLD}Available models:{C.RESET}\n")
    for m in models:
        tiny = m == config.model_tiny
        fast = m == config.model_fast
        strong = m == config.model_strong
        tag = (f" {C.CYAN}[tiny]{C.RESET}" if tiny else
               f" {C.GREEN}[fast]{C.RESET}" if fast else
               f" {C.YELLOW}[strong]{C.RESET}" if strong else "")
        marker = f"  {C.GREEN}●{C.RESET} " if (tiny or fast or strong) else "    "
        print(f"{marker}{m}{tag}")
    print(f"\n{C.DIM}tiny={config.model_tiny}  fast={config.model_fast}  strong={config.model_strong}{C.RESET}\n")


def cmd_config_show(config: Config) -> None:
    from dataclasses import asdict
    print(f"\n{C.CYAN}{C.BOLD}Current configuration:{C.RESET}\n")
    for k, v in asdict(config).items():
        print(f"  {C.WHITE}{k:<20}{C.RESET} {v}")
    from .config import CONFIG_FILE
    print(f"\n{C.DIM}Config file: {CONFIG_FILE}{C.RESET}\n")


def cmd_config_set(key: str, value: str, config: Config) -> None:
    from dataclasses import fields
    valid_keys = {f.name for f in fields(config)}
    if key not in valid_keys:
        print_error(f"Unknown config key: {key!r}")
        print_info(f"Valid keys: {', '.join(sorted(valid_keys))}")
        sys.exit(1)
    current = getattr(config, key)
    try:
        if isinstance(current, bool):
            typed = value.lower() in ("true", "1", "yes")
        elif isinstance(current, int):
            typed = int(value)
        else:
            typed = value
    except ValueError:
        print_error(f"Invalid value {value!r} for key {key!r}")
        sys.exit(1)
    setattr(config, key, typed)
    config.save()
    print_success(f"Set {key} = {typed!r}")


def cmd_stats() -> None:
    stats = compute_stats()
    if not stats:
        print_info("No telemetry data yet. Run some commands first.")
        return
    print(f"\n{C.CYAN}{C.BOLD}ShellAI telemetry (last 1000 requests):{C.RESET}\n")
    _kv = [
        ("Total requests",    stats.get("total_requests", 0)),
        ("Cache hit rate",    f"{stats.get('cache_hit_rate', 0):.1%}"),
        ("Execution rate",    f"{stats.get('execution_rate', 0):.1%}"),
        ("Success rate",      f"{stats.get('success_rate', 0):.1%}"),
        ("LLM calls made",    stats.get("llm_calls", 0)),
        ("Avg latency",       f"{stats.get('avg_latency_ms', 0):.0f} ms"),
        ("p50 latency",       f"{stats.get('p50_latency_ms', 0):.0f} ms"),
        ("p95 latency",       f"{stats.get('p95_latency_ms', 0):.0f} ms"),
    ]
    for label, val in _kv:
        print(f"  {C.WHITE}{label:<20}{C.RESET} {val}")
    if stats.get("model_usage"):
        print(f"\n  {C.DIM}Model usage:{C.RESET}")
        for m, n in stats["model_usage"].items():
            print(f"    {m:<30} {n}")
    if stats.get("tier_usage"):
        print(f"\n  {C.DIM}Tier usage:{C.RESET}")
        for t, n in stats["tier_usage"].items():
            print(f"    {t:<10} {n}")
    if stats.get("risk_distribution"):
        print(f"\n  {C.DIM}Risk distribution:{C.RESET}")
        for r, n in stats["risk_distribution"].items():
            print(f"    {r:<10} {n}")
    print()


def cmd_cache(clear: bool = False) -> None:
    cache = CommandCache(CONFIG_DIR / "cache.json")
    if clear:
        cache.clear()
        print_success("Cache cleared.")
        return
    s = cache.stats
    print(f"\n{C.CYAN}{C.BOLD}Command cache:{C.RESET}\n")
    print(f"  {'Entries':<20} {s['size']} / {s['max_size']}")
    print(f"  {'Hit rate':<20} {s['hit_rate']:.1%}  ({s['hits']} hits, {s['misses']} misses)")
    print(f"  {'TTL':<20} {s['ttl_seconds']}s\n")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _confirm(prompt: str, default: str = "n") -> bool:
    hint = " [y/N] " if default == "n" else " [Y/n] "
    try:
        answer = input(f"{C.BOLD}{prompt}{hint}{C.RESET}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not answer:
        return default == "y"
    return answer in ("y", "yes")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ai",
        description="ShellAI — Natural language terminal assistant powered by Ollama",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
        Examples:
          ai find files larger than 1GB
          ai shell                          # interactive REPL
          ai serve --port 8765             # start REST API
          ai stats                         # telemetry report
          ai cache --clear                 # flush cache
          ai --explain tar -czvf backup.tar.gz folder
          ai --set model_fast qwen2.5:1.5b
        """),
    )
    parser.add_argument("request", nargs="*", help="Natural language request or subcommand")
    parser.add_argument("--explain", "-e", action="store_true")
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--clear-history", action="store_true")
    parser.add_argument("--models", action="store_true")
    parser.add_argument("--model", "-m", metavar="NAME")
    parser.add_argument("--config", action="store_true")
    parser.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"))
    parser.add_argument("--version", "-v", action="version", version=f"shellai {__version__}")
    parser.add_argument("--url", metavar="URL")
    parser.add_argument("--no-confirm", action="store_true")
    parser.add_argument("--agentic", "-a", action="store_true",
                        help="Decompose request into a multi-step plan and execute sequentially")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="Auto-confirm all prompts (use with care)")
    # serve flags
    parser.add_argument("--port", type=int, metavar="N", help="Port for `ai serve`")
    parser.add_argument("--host", metavar="HOST", help="Host for `ai serve`")
    # cache flag
    parser.add_argument("--clear", action="store_true", help="Clear cache when used with `ai cache`")

    args = parser.parse_args()

    Config.init_dirs()
    config = Config.load()

    if args.model:
        config.model = config.model_tiny = config.model_fast = config.model_strong = args.model
    if args.url:
        config.ollama_url = args.url
    if args.no_confirm:
        config.confirm_safe = False

    # ── Subcommands that don't need Ollama ────────────────────────────────────
    if args.clear_history:
        clear_history()
        print_success("History cleared.")
        return

    if args.history:
        cmd_history()
        return

    if args.config:
        cmd_config_show(config)
        return

    if args.set:
        cmd_config_set(args.set[0], args.set[1], config)
        return

    # ── Positional subcommands ────────────────────────────────────────────────
    first = args.request[0] if args.request else None

    if first == "shell":
        from .repl import ShellAIRepl
        ShellAIRepl(config).run()
        return

    if first == "serve":
        from .server import ShellAIServer
        host = args.host or config.server_host
        port = args.port or config.server_port
        ShellAIServer(config, host=host, port=port).serve()
        return

    if first == "stats":
        cmd_stats()
        return

    if first == "cache":
        cmd_cache(clear=args.clear)
        return

    if not args.request:
        banner()
        parser.print_help()
        return

    # ── Commands that need Ollama ─────────────────────────────────────────────
    client = OllamaClient(config)

    if not client.is_available():
        print_error(f"Ollama is not running at {config.ollama_url}")
        print_info("Start it with:  ollama serve")
        sys.exit(1)

    if args.models:
        cmd_models(client, config)
        return

    request = " ".join(args.request)

    if args.explain and looks_like_command(request):
        cmd_explain(args.request, client, config)
        return

    # Agentic mode: explicit flag or auto-detected multi-step intent
    from .agent import ShellAIAgent, detect_agentic
    if args.agentic or detect_agentic(request):
        ShellAIAgent(config).run(request, auto_confirm=args.yes)
        return

    cmd_generate(request, client, config, args)


if __name__ == "__main__":
    main()

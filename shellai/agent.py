"""Tool-use agent loop for ShellAI.

The LLM is given a set of tools (run_command, write_file, read_file,
list_directory, search_files) and loops autonomously:

  user request
    → LLM reasons → calls tool
    → tool executes → result fed back
    → LLM reasons → calls next tool (or finishes)
    → done

This uses Ollama's native /api/chat tool-calling API.
Qwen3.5 supports tool use natively.

Usage
-----
    qwenshell --agentic write a C factorial program and run it
    qwenshell -a set up a python project with venv and install requests
    qwenshell -a find all TODO comments in this repo and summarise them
"""

import json
import re
import time
from typing import Optional

from .config import Config
from .display import C, print_error, print_info, print_step, print_success, print_warning
from .history import log_entry
from .metrics import build as build_metric, record
from .ollama_client import OllamaClient
from .safety import check_safety
from .tools import TOOL_SCHEMAS, execute_tool

MAX_ITERATIONS = 12   # prevent runaway loops

SYSTEM_PROMPT = """\
You are a powerful Linux/coding assistant with direct access to the user's system via tools.

You have these tools:
  run_command     — execute any shell command
  write_file      — create or overwrite any file
  read_file       — read any file
  list_directory  — list directory contents
  search_files    — find files by glob pattern

Workflow:
- Think step by step about what needs to be done
- Use tools to actually perform the work — don't just describe it
- After running a command, check its output before proceeding
- If a command fails, read the error and fix it
- When the task is complete, give a concise summary of what was done

Be autonomous. Complete the task fully without asking for confirmation on sub-steps."""

# Auto-detect when agentic mode should kick in
_CREATE_VERBS = {"write", "create", "make", "generate", "build", "setup",
                 "set up", "initialize", "init", "scaffold", "code", "implement"}
_ACTION_VERBS = {"compile", "run", "execute", "test", "install", "deploy",
                 "start", "launch", "lint", "format", "push", "fix", "debug"}


def detect_agentic(request: str) -> bool:
    """Return True if the request likely needs multi-step tool use."""
    text = request.lower()
    words = set(re.findall(r"\w+", text))
    if (words & _CREATE_VERBS) and (words & _ACTION_VERBS):
        return True
    if any(p in text for p in ("and then", "then run", "then compile",
                                "then execute", "and run", "and compile",
                                "and install", "after that", "also run")):
        return True
    return False


class ShellAIAgent:
    """Autonomous tool-use agent powered by Ollama tool calling."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.client = OllamaClient(config)
        self.client.model = config.model_strong  # use strongest model for agent

    def run(self, request: str, auto_confirm: bool = False) -> None:
        print_step(f"Agent: {C.WHITE}{request}{C.RESET}")
        print_info(f"model={C.WHITE}{self.config.model_strong}{C.RESET}  "
                   f"tools={len(TOOL_SCHEMAS)}  max_iter={MAX_ITERATIONS}")
        print()

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": request},
        ]

        t0 = time.monotonic()
        iterations = 0
        tool_calls_total = 0

        while iterations < MAX_ITERATIONS:
            iterations += 1

            # Call LLM with tools
            response_msg = self.client.chat_with_tools(messages, TOOL_SCHEMAS)

            tool_calls = response_msg.get("tool_calls") or []
            content = (response_msg.get("content") or "").strip()

            # No tool calls — LLM is done
            if not tool_calls:
                if content:
                    print(f"\n{C.WHITE}{content}{C.RESET}\n")
                print_success(
                    f"Done  ({iterations} iteration{'s' if iterations > 1 else ''}, "
                    f"{tool_calls_total} tool call{'s' if tool_calls_total != 1 else ''}, "
                    f"{(time.monotonic() - t0):.1f}s)"
                )
                break

            # Add assistant message with tool calls
            messages.append(response_msg)

            # Execute each tool call
            for tc in tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "")
                raw_args = fn.get("arguments", {})
                args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args)

                tool_calls_total += 1
                self._display_tool_call(tool_name, args)

                # Safety gate on run_command
                if tool_name == "run_command":
                    cmd = args.get("command", "")
                    safety = check_safety(cmd)
                    if not safety.safe:
                        result = {"error": f"Blocked by safety filter: {safety.reason}"}
                        print_warning(f"  blocked: {safety.reason}")
                    else:
                        result = execute_tool(tool_name, args)
                else:
                    result = execute_tool(tool_name, args)

                self._display_tool_result(tool_name, args, result)

                # Feed result back to LLM
                messages.append({
                    "role": "tool",
                    "content": json.dumps(result),
                })

        else:
            print_warning(f"Reached max iterations ({MAX_ITERATIONS}). Stopping.")

        latency_ms = (time.monotonic() - t0) * 1000
        log_entry(request, f"[agent:{tool_calls_total} tools]",
                  executed=True, returncode=0, config=self.config)
        record(build_metric(
            request=request,
            command=f"[agent:{tool_calls_total} tools]",
            model=self.config.model_strong,
            tier="strong",
            latency_ms=latency_ms,
            cache_hit=False,
            risk_level="safe",
            executed=True,
            returncode=0,
            source="agent",
        ))

    # ── Display helpers ────────────────────────────────────────────────────────

    def _display_tool_call(self, name: str, args: dict) -> None:
        icons = {
            "run_command": "⚡",
            "write_file": "✍",
            "read_file": "📖",
            "list_directory": "📂",
            "search_files": "🔍",
        }
        icon = icons.get(name, "🔧")
        print(f"{C.CYAN}{icon} {name}{C.RESET}", end="  ")
        if name == "run_command":
            print(f"{C.YELLOW}{args.get('command', '')}{C.RESET}")
        elif name == "write_file":
            content = args.get("content", "")
            lines = content.count("\n") + 1
            print(f"{C.WHITE}{args.get('path', '')} {C.DIM}({lines} lines){C.RESET}")
        elif name == "read_file":
            print(f"{C.WHITE}{args.get('path', '')}{C.RESET}")
        elif name == "list_directory":
            print(f"{C.WHITE}{args.get('path', '.')}{C.RESET}")
        elif name == "search_files":
            print(f"{C.WHITE}{args.get('pattern', '')} in {args.get('path', '.')}{C.RESET}")
        else:
            print(f"{C.DIM}{args}{C.RESET}")

    def _display_tool_result(self, name: str, args: dict, result: dict) -> None:
        if "error" in result:
            print(f"  {C.RED}✗ {result['error']}{C.RESET}")
        elif name == "run_command":
            rc = result.get("exit_code", 0)
            color = C.GREEN if rc == 0 else C.RED
            mark = "✔" if rc == 0 else "✗"
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            print(f"  {color}{mark} exit {rc}{C.RESET}", end="")
            if stdout:
                preview = stdout[:200] + ("…" if len(stdout) > 200 else "")
                print(f"  {C.DIM}{preview}{C.RESET}", end="")
            if stderr and rc != 0:
                preview = stderr[:200] + ("…" if len(stderr) > 200 else "")
                print(f"\n  {C.RED}{preview}{C.RESET}", end="")
            print()
        elif name == "write_file":
            print(f"  {C.GREEN}✔ wrote {result.get('bytes', '?')} bytes → {result.get('path', '')}{C.RESET}")
        elif name == "read_file":
            lines = result.get("lines", "?")
            print(f"  {C.GREEN}✔ read {lines} lines{C.RESET}")
        elif name == "list_directory":
            count = result.get("count", 0)
            print(f"  {C.GREEN}✔ {count} entries{C.RESET}")
        elif name == "search_files":
            count = result.get("count", 0)
            print(f"  {C.GREEN}✔ {count} matches{C.RESET}")
        print()

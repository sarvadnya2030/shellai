"""Terminal color and formatting utilities for ShellAI."""

import sys
import os

# Detect color support
_NO_COLOR = os.getenv("NO_COLOR") or not sys.stdout.isatty()


class C:
    """ANSI color codes — disabled automatically when not in a TTY."""

    RESET  = "" if _NO_COLOR else "\033[0m"
    BOLD   = "" if _NO_COLOR else "\033[1m"
    DIM    = "" if _NO_COLOR else "\033[2m"

    # Foreground
    RED    = "" if _NO_COLOR else "\033[91m"
    GREEN  = "" if _NO_COLOR else "\033[92m"
    YELLOW = "" if _NO_COLOR else "\033[93m"
    BLUE   = "" if _NO_COLOR else "\033[94m"
    MAGENTA= "" if _NO_COLOR else "\033[95m"
    CYAN   = "" if _NO_COLOR else "\033[96m"
    WHITE  = "" if _NO_COLOR else "\033[97m"
    GRAY   = "" if _NO_COLOR else "\033[90m"

    # Background
    BG_DARK = "" if _NO_COLOR else "\033[40m"


def banner() -> None:
    """Print the ShellAI banner."""
    print(f"""
{C.CYAN}{C.BOLD}  ╔══════════════════════════════╗
  ║   🤖  S H E L L  A I        ║
  ║   Natural Language Terminal  ║
  ╚══════════════════════════════╝{C.RESET}
""")


def print_command_box(command: str, risk_level: str = "safe") -> None:
    """Pretty-print the suggested command."""
    risk_colors = {
        "safe":     C.GREEN,
        "medium":   C.YELLOW,
        "high":     C.YELLOW,
        "critical": C.RED,
    }
    color = risk_colors.get(risk_level, C.WHITE)
    border = "─" * (len(command) + 4)
    print(f"\n  {C.DIM}┌{border}┐{C.RESET}")
    print(f"  {C.DIM}│{C.RESET}  {color}{C.BOLD}{command}{C.RESET}  {C.DIM}│{C.RESET}")
    print(f"  {C.DIM}└{border}┘{C.RESET}\n")


def print_success(msg: str) -> None:
    print(f"{C.GREEN}✔ {msg}{C.RESET}")


def print_error(msg: str) -> None:
    print(f"{C.RED}✗ {msg}{C.RESET}", file=sys.stderr)


def print_warning(msg: str) -> None:
    print(f"{C.YELLOW}⚠ {msg}{C.RESET}")


def print_info(msg: str) -> None:
    print(f"{C.CYAN}ℹ {msg}{C.RESET}")


def print_step(step: str) -> None:
    print(f"{C.BLUE}→ {step}{C.RESET}")


def print_blocked(reason: str) -> None:
    print(f"\n{C.RED}{C.BOLD}🚫 BLOCKED — {reason}{C.RESET}")
    print(f"{C.DIM}  This command was flagged as potentially dangerous.{C.RESET}\n")


def print_risk_warning(reason: str, level: str) -> None:
    level_icons = {"medium": "⚠", "high": "🔶"}
    icon = level_icons.get(level, "⚠")
    color = C.YELLOW if level == "medium" else C.RED
    print(f"{color}{icon}  Risk: {reason}{C.RESET}")


def spinner_frames() -> list[str]:
    return ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def thinking_spinner(message: str = "Thinking") -> "Spinner":
    return Spinner(message)


class Spinner:
    """Simple terminal spinner context manager."""

    def __init__(self, message: str):
        self.message = message
        self._active = False
        self._thread = None

    def __enter__(self):
        if sys.stdout.isatty():
            import threading, itertools, time
            self._active = True
            frames = spinner_frames()
            def _spin():
                for frame in itertools.cycle(frames):
                    if not self._active:
                        break
                    print(f"\r{C.CYAN}{frame}{C.RESET}  {self.message}...", end="", flush=True)
                    import time; time.sleep(0.08)
                print("\r" + " " * (len(self.message) + 10) + "\r", end="", flush=True)
            self._thread = threading.Thread(target=_spin, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *_):
        self._active = False
        if self._thread:
            self._thread.join(timeout=1)

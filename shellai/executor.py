"""Shell command executor for ShellAI."""

import os
import subprocess
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecutionResult:
    returncode: int
    stdout: str
    stderr: str
    duration: float
    command: str

    @property
    def success(self) -> bool:
        return self.returncode == 0


def run_command(command: str, timeout: int = 60, cwd: Optional[str] = None) -> ExecutionResult:
    """
    Execute a shell command and return the result.
    Uses the user's current working directory by default.
    """
    cwd = cwd or os.getcwd()
    start = time.monotonic()

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env={**os.environ},   # inherit full environment
        )
        duration = time.monotonic() - start
        return ExecutionResult(
            returncode=result.returncode,
            stdout=result.stdout.strip(),
            stderr=result.stderr.strip(),
            duration=duration,
            command=command,
        )
    except subprocess.TimeoutExpired:
        return ExecutionResult(
            returncode=124,
            stdout="",
            stderr=f"Command timed out after {timeout}s",
            duration=timeout,
            command=command,
        )
    except Exception as e:
        return ExecutionResult(
            returncode=1,
            stdout="",
            stderr=str(e),
            duration=time.monotonic() - start,
            command=command,
        )


def stream_command(command: str, timeout: int = 60, cwd: Optional[str] = None) -> int:
    """
    Execute a command and stream stdout/stderr directly to the terminal.
    Returns the exit code.
    """
    cwd = cwd or os.getcwd()
    try:
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=cwd,
            env={**os.environ},
        )
        proc.wait(timeout=timeout)
        return proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        print(f"\n\033[91m✗ Command timed out after {timeout}s\033[0m")
        return 124
    except KeyboardInterrupt:
        proc.kill()
        print("\n\033[93m⚡ Interrupted\033[0m")
        return 130

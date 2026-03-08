"""Tool registry and executor for the ShellAI agent.

The LLM is given these tools and can call them in any order, as many times
as needed, until the task is complete.

Tools
-----
  run_command     execute a shell command; returns stdout, stderr, exit_code
  write_file      create or overwrite a file with given content
  read_file       read a file's contents
  list_directory  list files in a directory
  search_files    find files matching a glob pattern
"""

import glob
import os
import subprocess
import time
from pathlib import Path
from typing import Any


# ── Tool schemas (sent to Ollama /api/chat) ───────────────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Execute a shell command on the user's Linux system. "
                "Returns stdout, stderr, and exit_code. "
                "Use this to compile code, run scripts, install packages, "
                "check system state, or perform any shell operation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create or overwrite a file with the given content. "
                "Use this to write source code, scripts, configs, or any text file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to write (relative or absolute)",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full content to write to the file",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read and return the contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to read",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List files and directories at a given path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list (default: current directory)",
                        "default": ".",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for files matching a glob pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern, e.g. '**/*.py' or '*.c'",
                    },
                    "path": {
                        "type": "string",
                        "description": "Root directory to search from (default: current directory)",
                        "default": ".",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
]


# ── Tool executor ─────────────────────────────────────────────────────────────

def execute_tool(name: str, args: dict) -> dict[str, Any]:
    """Dispatch a tool call and return a result dict."""
    match name:
        case "run_command":
            return _run_command(args.get("command", ""))
        case "write_file":
            return _write_file(args.get("path", ""), args.get("content", ""))
        case "read_file":
            return _read_file(args.get("path", ""))
        case "list_directory":
            return _list_directory(args.get("path", "."))
        case "search_files":
            return _search_files(args.get("pattern", "*"), args.get("path", "."))
        case _:
            return {"error": f"Unknown tool: {name}"}


def _run_command(command: str) -> dict:
    if not command.strip():
        return {"error": "Empty command"}
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True,
            text=True, timeout=60, cwd=os.getcwd(),
        )
        return {
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out after 60s", "exit_code": 124}
    except Exception as e:
        return {"error": str(e), "exit_code": 1}


def _write_file(path: str, content: str) -> dict:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return {"ok": True, "path": str(p.resolve()), "bytes": len(content)}
    except Exception as e:
        return {"error": str(e)}


def _read_file(path: str) -> dict:
    try:
        content = Path(path).read_text()
        return {"content": content, "lines": content.count("\n") + 1}
    except FileNotFoundError:
        return {"error": f"File not found: {path}"}
    except Exception as e:
        return {"error": str(e)}


def _list_directory(path: str) -> dict:
    try:
        entries = sorted(os.listdir(path))
        result = []
        for e in entries:
            full = os.path.join(path, e)
            result.append({
                "name": e,
                "type": "dir" if os.path.isdir(full) else "file",
                "size": os.path.getsize(full) if os.path.isfile(full) else None,
            })
        return {"entries": result, "count": len(result)}
    except Exception as e:
        return {"error": str(e)}


def _search_files(pattern: str, path: str) -> dict:
    try:
        root = Path(path)
        matches = [str(p) for p in root.glob(pattern)]
        return {"matches": sorted(matches), "count": len(matches)}
    except Exception as e:
        return {"error": str(e)}

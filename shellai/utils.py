"""Shared utilities for ShellAI."""

import re


def clean_llm_command(raw: str) -> str:
    """Strip markdown fences, leading $, extra whitespace from LLM output."""
    raw = raw.strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    raw = re.sub(r"^`|`$", "", raw)
    raw = re.sub(r"^\$\s+", "", raw)
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return ""
    first = lines[0]
    if len(lines) > 1 and first.endswith(":"):
        first = lines[1]
    return first


def looks_like_command(text: str) -> bool:
    """Heuristic: does this string look like a shell command?"""
    if not text:
        return False
    first_word = text.split()[0].lstrip("./")
    known_starters = {
        "find", "ls", "grep", "du", "df", "ps", "top", "cat", "echo",
        "mkdir", "cp", "mv", "rm", "tar", "gzip", "zip", "unzip", "curl",
        "wget", "apt", "apt-get", "snap", "pip", "pip3", "python", "python3",
        "systemctl", "journalctl", "docker", "git", "ssh", "scp", "rsync",
        "chmod", "chown", "ln", "wc", "sort", "uniq", "head", "tail", "awk",
        "sed", "xargs", "tee", "cut", "tr", "diff", "file", "stat", "lsof",
        "netstat", "ss", "ping", "traceroute", "nmap", "kill", "pkill",
        "nginx", "apache2", "service", "crontab", "env", "export", "source",
        "ffmpeg", "convert", "identify", "npm", "node", "cargo", "go",
    }
    return first_word.lower() in known_starters or text.startswith("/")

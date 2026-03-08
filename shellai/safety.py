"""Safety filter to block dangerous shell commands."""

import re
import shlex
from dataclasses import dataclass
from typing import Optional


@dataclass
class SafetyResult:
    safe: bool
    reason: Optional[str] = None
    risk_level: str = "safe"   # safe | low | medium | high | critical


# ── Pattern-based blocklist ────────────────────────────────────────────────────

# Critical: always block, no override
CRITICAL_PATTERNS = [
    # Fork bomb
    (r":\(\)\s*\{.*\|.*:.*&.*\}", "Fork bomb detected"),
    # Wipe entire disk/partition
    (r"\bdd\b.*\bof\s*=\s*/dev/(sd|hd|nvme|vd)[a-z]", "Disk wipe via dd"),
    # Format filesystems
    (r"\bmkfs\b", "Filesystem format command"),
    # Recursive root delete
    (r"\brm\b.*-[a-zA-Z]*r[a-zA-Z]*.*\s+/(\s|$)", "Recursive root deletion"),
    (r"\brm\b.*--no-preserve-root", "Root deletion bypass"),
    # Overwrite core system files
    (r">\s*/etc/(passwd|shadow|sudoers|fstab|hosts)", "Overwrite critical system file"),
    # Kernel / boot wiper
    (r"\brm\b.*/boot/", "Deleting boot partition files"),
    # Shutdown / reboot (blocking by default — user can always run these directly)
    (r"\b(shutdown|reboot|poweroff|halt|init\s+[06])\b", "System shutdown/reboot"),
]

# High risk: warn strongly
HIGH_RISK_PATTERNS = [
    (r"\brm\b.*-[a-zA-Z]*r", "Recursive deletion"),
    (r"\bchmod\b.*777\b", "World-writable permissions"),
    (r"\bchown\b.*root", "Changing ownership to root"),
    (r"\b(curl|wget)\b.*\|\s*(ba)?sh\b", "Pipe download to shell (code execution)"),
    (r"\bsudo\b", "Elevated privileges required"),
    (r"\bkill\b.*-9.*\$\(", "Mass process kill via subshell"),
    (r">\s*/dev/sd", "Writing directly to block device"),
]

# Medium risk: warn, still ask confirmation
MEDIUM_RISK_PATTERNS = [
    (r"\brm\b", "File deletion"),
    (r"\bmv\b.*/(etc|usr|bin|sbin|lib)\b", "Moving system directory"),
    (r"\btruncate\b", "Truncating files"),
    (r"\bcrontab\b.*-r", "Removing crontab"),
    (r"\biptables\b", "Modifying firewall rules"),
    (r"\bufw\b", "Modifying firewall rules"),
    (r"\bsystemctl\b.*(stop|disable|mask)\b", "Disabling system service"),
]


def _check_patterns(command: str, patterns: list[tuple[str, str]]) -> Optional[tuple[str, str]]:
    """Return (pattern_matched, reason) if any pattern matches."""
    for pattern, reason in patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return pattern, reason
    return None


def check_safety(command: str) -> SafetyResult:
    """Analyse a shell command and return a SafetyResult."""
    command = command.strip()

    if not command:
        return SafetyResult(safe=False, reason="Empty command", risk_level="safe")

    # Try to detect obvious attempts to obfuscate commands
    if _looks_obfuscated(command):
        return SafetyResult(
            safe=False,
            reason="Obfuscated command detected",
            risk_level="critical",
        )

    match = _check_patterns(command, CRITICAL_PATTERNS)
    if match:
        return SafetyResult(safe=False, reason=match[1], risk_level="critical")

    match = _check_patterns(command, HIGH_RISK_PATTERNS)
    if match:
        return SafetyResult(safe=True, reason=match[1], risk_level="high")

    match = _check_patterns(command, MEDIUM_RISK_PATTERNS)
    if match:
        return SafetyResult(safe=True, reason=match[1], risk_level="medium")

    return SafetyResult(safe=True, risk_level="safe")


def _looks_obfuscated(command: str) -> bool:
    """Heuristic to detect base64 eval tricks, hex encoding, etc."""
    obfuscation_patterns = [
        r"\beval\b.*\$\(",          # eval $(...)
        r"\bbase64\b.*--decode.*\|\s*(ba)?sh",
        r"\becho\b.*\|\s*base64.*\|\s*(ba)?sh",
        r"\\x[0-9a-fA-F]{2}",      # hex encoded chars
        r"\$\'\\\d{3}",             # octal escape sequences
    ]
    for pat in obfuscation_patterns:
        if re.search(pat, command, re.IGNORECASE):
            return True
    return False


def sanitize_for_display(command: str) -> str:
    """Return command with sensitive-looking tokens masked."""
    # Mask anything that looks like a token/password env var
    return re.sub(r'(PASSWORD|TOKEN|SECRET|KEY)=\S+', r'\1=***', command, flags=re.IGNORECASE)

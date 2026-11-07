"""Best-effort detection of CLI parser errors in raw network-device output."""
from __future__ import annotations
import re

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_ERROR_PATTERNS = (
    re.compile(r"^\s*(?:\[[^\]\r\n]+\]\s*)?(?:error\s*:\s*(?:unrecognized command|unknown command|incomplete command|wrong parameter|too many parameters?|ambiguous command|invalid input)\b|unrecognized command\b|unknown command\b|incomplete command\b|wrong parameter\b|too many parameters?\b|ambiguous command\b)", re.I),
    re.compile(r"^\s*(?:\[[^\]\r\n]+\]\s*)?%\s*(?:invalid input|incomplete command|ambiguous command|unrecognized command)", re.I),
    re.compile(r"^\s*(?:\[[^\]\r\n]+\]\s*)?(?:命令错误|未知命令|命令不完整|参数错误|错误\s*[:：])"),
    re.compile(r"unrecognized command found at\s*['\"]?\^", re.I),
    re.compile(r"incomplete command found at\s*['\"]?\^", re.I),
    re.compile(r"wrong parameter found at\s*['\"]?\^", re.I),
)


def clean_cli_output(output: str) -> str:
    """Remove terminal colour sequences without changing device text otherwise."""
    return _ANSI_RE.sub("", output or "")


def detect_device_error(output: str) -> dict | None:
    """Return the first parser/error line, or None when no known error is found.

    This is intentionally conservative: it looks for known error signatures at
    line start (or the common VRP caret diagnostic) instead of any occurrence
    of the word "error" in normal counters or descriptions.
    """
    cleaned = clean_cli_output(output)
    for line in cleaned.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        for pattern in _ERROR_PATTERNS:
            if pattern.search(candidate):
                return {"line": candidate[:500], "detector": pattern.pattern}
    return None

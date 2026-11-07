"""Normalize vendor CLI configuration wrappers before validation or dispatch."""
from __future__ import annotations
import re

_ENTER_CONFIG_VIEW = frozenset({
    "system-view", "system view", "sys", "configure terminal", "conf t",
    "config terminal", "config",
})
_EXIT_CONFIG_VIEW = frozenset({"return", "end", "exit", "quit"})


def _key(command: str) -> str:
    return re.sub(r"\s+", " ", command.strip()).casefold()


def normalize_config_commands(commands: list[str] | tuple[str, ...]) -> list[str]:
    """Remove only outer view wrappers; retain intermediate `quit` commands.

    Netmiko enters and exits config mode itself. A leading system-view and
    trailing return/quit are therefore wrappers, while an intermediate quit
    is meaningful on VRP (for example, leaving interface view).
    """
    normalized = [str(command).strip() for command in commands if str(command).strip()]
    start = 0
    while start < len(normalized) and _key(normalized[start]) in _ENTER_CONFIG_VIEW:
        start += 1
    end = len(normalized)
    while end > start and _key(normalized[end - 1]) in _EXIT_CONFIG_VIEW:
        end -= 1
    return normalized[start:end]

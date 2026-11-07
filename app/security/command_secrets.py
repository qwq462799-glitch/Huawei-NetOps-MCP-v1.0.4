"""Resolve protected command placeholders and redact their literal values from output."""
from __future__ import annotations

import os
import re
from pathlib import Path

from dotenv import dotenv_values

from app.security.redaction import redact_text

_PLACEHOLDER = re.compile(r"\$\{(NETOPS_SECRET_[A-Z0-9_]{1,80})\}")
_PROJECT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def _secret_environment() -> dict[str, str]:
    """Load project .env as fallback; protected process environment has priority."""
    values = {
        key: str(value)
        for key, value in dotenv_values(_PROJECT_ENV_FILE).items()
        if value is not None
    }
    values.update({key: str(value) for key, value in os.environ.items()})
    return values


def command_secret_values(commands: list[str]) -> dict[str, str]:
    """Return values referenced by command placeholders, without exposing them in errors."""
    env_values = _secret_environment()
    names = {
        match.group(1)
        for command in commands
        for match in _PLACEHOLDER.finditer(command)
    }
    return {
        name: env_values[name]
        for name in names
        if env_values.get(name) not in (None, "")
    }


def resolve_command_secrets(commands: list[str]) -> list[str]:
    """Resolve ${NETOPS_SECRET_NAME}; reject missing or unsafe values before execution."""
    values = command_secret_values(commands)
    resolved = []
    for command in commands:
        def replace(match: re.Match) -> str:
            name = match.group(1)
            value = values.get(name)
            if value is None or value == "":
                raise ValueError(f"配置命令引用的密钥环境变量未设置：{name}")
            if any(char in value for char in ("\n", "\r", "\x00", ";", "|", ">", "<")):
                raise ValueError(f"密钥环境变量 {name} 包含不允许的换行/分隔符（命令注入字符）")
            if len(value) > 256:
                raise ValueError(f"密钥环境变量 {name} 超过 256 字符")
            return value

        resolved.append(_PLACEHOLDER.sub(replace, command))
    return resolved


def redact_command_secrets(
    value: str | None,
    commands: list[str],
    secret_values: list[str] | tuple[str, ...] | None = None,
) -> str:
    """Mask exact referenced and transaction-snapshotted values, then generic CLI fields."""
    text = "" if value is None else str(value)
    secrets = set(command_secret_values(commands).values())
    secrets.update(str(item) for item in (secret_values or []) if item)
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            text = text.replace(secret, "<REDACTED>")
    return redact_text(text)

"""Shared argument coercion for MCP tool parameters.

Some MCP clients (including DSH) may serialize a list argument as a JSON
string instead of sending a real array. Pydantic would then reject the call
with `Input should be a valid list`, which is confusing because the payload
is semantically correct. Coerce those strings back into lists here so the
tool behaves the same regardless of client serialization quirks.
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Iterable

from pydantic import BeforeValidator


def _coerce_str_list(value: Any) -> Any:
    """Accept a real list, a tuple, or a JSON-encoded string list."""
    if value is None:
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"命令列表必须是字符串数组，无法解析 JSON：{exc}") from exc
        if not isinstance(parsed, list):
            raise ValueError("命令列表必须是字符串数组")
        return parsed
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict)):
        return list(value)
    return value


def _ensure_str_items(value: Any) -> list[str]:
    if value is None:
        return []
    items = _coerce_str_list(value)
    if not isinstance(items, list):
        raise ValueError("命令列表必须是字符串数组")
    result: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise ValueError("命令列表中的每一项都必须是字符串")
        if item.strip():
            result.append(item)
    return result


StrList = Annotated[list[str], BeforeValidator(_ensure_str_items)]
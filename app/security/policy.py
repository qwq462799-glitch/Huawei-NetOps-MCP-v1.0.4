from __future__ import annotations

import re

# 明确拒绝的高危命令关键字。此规则是纵深防御，不替代设备侧 AAA 权限。
DENY_PATTERNS = [
    r"\breboot\b", r"\breset\s+saved-configuration\b",
    r"\bformat\b", r"\bdelete\b", r"\bundo\s+.*(aaa|user-interface)",
    r"\bwrite\s+erase\b", r"\berase\s+startup-config\b",
    r"^\s*shutdown(?:\s+.*)?$",
]
READ_ONLY_PREFIXES = (
    "display ", "show ", "ping ", "tracert ", "traceroute ",
    "terminal ", "screen-length ",
)

# Permit only non-mutating display filters. An arbitrary pipe tail can execute
# redirection/export subcommands on some network operating systems.
READ_ONLY_PIPE_FILTERS = frozenset({
    "include", "exclude", "begin", "section", "count", "no-more",
    "inc", "exc", "beg",
})


def classify_command(command: str) -> str:
    cmd = command.strip().lower()
    # Read-only query filters may legitimately contain words such as "shutdown".
    if cmd.startswith(READ_ONLY_PREFIXES):
        return "read"
    if any(re.search(pattern, cmd) for pattern in DENY_PATTERNS):
        return "denied"
    return "write"


def _validate_read_pipeline(command: str) -> None:
    if "|" not in command:
        return
    if command.count("|") != 1:
        raise ValueError("只读命令最多允许一个管道过滤器")
    left, right = command.split("|", 1)
    if classify_command(left) != "read":
        raise ValueError("管道左侧必须是只读查询命令")
    if any(char in right for char in ("<", ">", ";", "&", "`", "\\", "\x00")):
        raise ValueError("管道过滤器包含重定向或命令注入字符")
    filter_name = right.strip().split(maxsplit=1)[0].lower() if right.strip() else ""
    if filter_name not in READ_ONLY_PIPE_FILTERS:
        raise ValueError(
            "不允许的管道操作；只允许 include/exclude/begin/section/count/no-more 等只读过滤器"
        )


def validate_command(command: str, allow_write: bool = False):
    if not isinstance(command, str):
        raise ValueError("命令必须是字符串")
    # 每个 MCP 参数只允许一条 CLI 命令，禁止换行/分号把多条命令伪装成只读命令。
    if any(char in command for char in ("\n", "\r", "\x00", ";", ">", "<", "&", "`")) or "$((" in command or "$(" in command:
        raise ValueError("单条命令不得包含换行、空字符、分号或重定向符号")
    if not command.strip() or len(command) > 500:
        raise ValueError("命令为空或长度超过限制")
    kind = classify_command(command)
    if kind == "denied":
        raise ValueError("命令命中高危策略，已拒绝执行")
    if kind == "read":
        _validate_read_pipeline(command)
    elif "|" in command:
        raise ValueError("配置写命令不得使用管道符")
    if kind == "write" and not allow_write:
        raise PermissionError("当前为只读模式；写命令必须先创建并通过审批")
    return kind

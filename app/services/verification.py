"""Configuration verification assertions with backwards-compatible semantics."""
from __future__ import annotations
import re
from app.security.device_output import clean_cli_output, detect_device_error

_WHITESPACE_RE = re.compile(r"\s+")
_MAX_ASSERTIONS = 20
_MAX_PATTERN_LENGTH = 256


def _normalise_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def validate_assertions(
    expected_output_contains: str = "",
    expected_output_contains_all: list[str] | None = None,
    expected_output_not_contains: list[str] | None = None,
    expected_output_regex: list[str] | None = None,
) -> dict:
    contains_all = [v.strip() for v in (expected_output_contains_all or []) if v and v.strip()]
    not_contains = [v.strip() for v in (expected_output_not_contains or []) if v and v.strip()]
    regexes = [v.strip() for v in (expected_output_regex or []) if v and v.strip()]
    contains = (expected_output_contains or "").strip()
    if len(contains) > 500:
        raise ValueError("expected_output_contains 长度不能超过 500 字符")
    for name, values in (
        ("expected_output_contains_all", contains_all),
        ("expected_output_not_contains", not_contains),
        ("expected_output_regex", regexes),
    ):
        if len(values) > _MAX_ASSERTIONS:
            raise ValueError(f"{name} 最多允许 {_MAX_ASSERTIONS} 条断言")
        if any(len(value) > 500 for value in values):
            raise ValueError(f"{name} 中的每条文本不能超过 500 字符")
    if any(len(pattern) > _MAX_PATTERN_LENGTH for pattern in regexes):
        raise ValueError(f"正则表达式长度不能超过 {_MAX_PATTERN_LENGTH} 字符")
    for pattern in regexes:
        # Python's backtracking regex engine has no per-search timeout. Reject
        # common catastrophic-backtracking constructs before they can stall MCP.
        unsafe_patterns = (
            r"\([^)]*[+*{][^)]*\)[+*{]",  # quantified group containing a quantifier
            r"\([^)]*\|[^)]*\)[+*{]",  # quantified alternation group
            r"\\[1-9]",                    # backreferences
            r"\(\?",                        # lookarounds / inline engine controls
        )
        if any(re.search(rule, pattern) for rule in unsafe_patterns):
            raise ValueError("验证正则包含高风险回溯/高级构造，请改用简单、明确的匹配表达式")
        try:
            re.compile(pattern, re.IGNORECASE | re.MULTILINE)
        except re.error as exc:
            raise ValueError(f"无效的验证正则表达式 {pattern!r}：{exc}") from exc
    if not (contains or contains_all or not_contains or regexes):
        raise ValueError("至少提供一条验证断言：包含、不包含或正则表达式")
    return {
        "expected_output_contains": contains,
        "expected_output_contains_all": contains_all,
        "expected_output_not_contains": not_contains,
        "expected_output_regex": regexes,
    }


def evaluate_assertions(
    output: str,
    expected_output_contains: str = "",
    expected_output_contains_all: list[str] | None = None,
    expected_output_not_contains: list[str] | None = None,
    expected_output_regex: list[str] | None = None,
) -> dict:
    """All supplied assertions must pass; literals compare with whitespace collapsed."""
    raw = clean_cli_output(output or "")
    compact = _normalise_text(raw)
    contains_all = expected_output_contains_all or []
    not_contains = expected_output_not_contains or []
    regexes = expected_output_regex or []
    checks: list[dict] = []
    has_truncation_marker = "..." in raw or "…" in raw

    def literal_check(kind: str, value: str, should_exist: bool) -> None:
        needle = _normalise_text(value)
        found = needle in compact
        # 负向断言遇到省略号时不能安全证明“对象不存在”：被截掉的部分
        # 可能正好包含目标对象，因此 fail closed，要求调用方改用定向查询。
        inconclusive = (not should_exist) and has_truncation_marker
        passed = (found if should_exist else not found) and not inconclusive
        check = {"type": kind, "expected": value, "matched": found, "passed": passed}
        if inconclusive:
            check["inconclusive"] = True
            check["detail"] = "设备输出含省略号，无法用当前回显证明目标内容不存在；请使用定向查询。"
        checks.append(check)

    if expected_output_contains:
        literal_check("contains", expected_output_contains, True)
    for value in contains_all:
        literal_check("contains_all", value, True)
    for value in not_contains:
        literal_check("not_contains", value, False)
    for pattern in regexes:
        matched = re.search(pattern, raw, re.IGNORECASE | re.MULTILINE) is not None
        checks.append({"type": "regex", "expected": pattern, "matched": matched, "passed": matched})

    cli_error = detect_device_error(raw)
    if cli_error:
        checks.append({"type": "device_cli_error", "expected": "no device CLI error", "matched": True, "passed": False,
                       "detail": cli_error["line"]})

    passed = bool(checks) and all(item["passed"] for item in checks)
    truncation_suspected = has_truncation_marker and (not passed or bool(not_contains))
    warnings = []
    if truncation_suspected:
        warnings.append(
            "设备回显包含省略号，断言结果可能受设备侧字段/输出截断影响；尤其不能据此证明配置对象已删除。请改用针对具体对象的定向查询。"
        )
    return {
        "passed": passed,
        "checks": checks,
        "failed_checks": [item for item in checks if not item["passed"]],
        "device_error": cli_error,
        "truncation_suspected": truncation_suspected,
        "warnings": warnings,
        "matching_note": "文本断言会先移除 ANSI 颜色码并折叠连续空白；正则默认忽略大小写并启用多行匹配。",
    }

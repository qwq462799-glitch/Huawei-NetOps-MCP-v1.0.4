"""Read-only diff between a transaction's encrypted pre-change snapshot and live config."""
from __future__ import annotations

import difflib

from app.security.credentials import decrypt_secret
from app.security.redaction import redact_text
from app.services.device_service import _snapshot_command, execute
from app.storage import get_device, get_transaction


def diff_transaction(transaction_id: str, max_lines: int = 1200) -> dict:
    tx = get_transaction(transaction_id)
    if not tx:
        return {"success": False, "error": "变更事务不存在", "transaction_id": transaction_id}
    if not tx.get("snapshot_encrypted"):
        return {"success": False, "error": "该事务没有可用的变更前加密快照", "transaction_id": transaction_id}
    device = get_device(tx["device_id"])
    if not device:
        return {"success": False, "error": "设备记录不存在", "transaction_id": transaction_id}
    try:
        baseline = decrypt_secret(tx["snapshot_encrypted"])
    except Exception as exc:
        return {
            "success": False,
            "error": "快照无法解密；请确认使用创建该快照时的 CREDENTIAL_ENCRYPTION_KEY。",
            "detail": type(exc).__name__,
            "transaction_id": transaction_id,
        }

    current_result = execute(tx["device_id"], _snapshot_command(device["vendor"]))
    if not current_result.get("success"):
        return {
            "success": False,
            "error": "读取设备当前配置失败，未生成差异。",
            "device_result": current_result,
            "transaction_id": transaction_id,
        }
    # Redact secrets before creating a diff so a changed secret cannot leak in the result.
    before_lines = redact_text(baseline).splitlines()
    current_lines = redact_text(current_result.get("output", "")).splitlines()
    diff_lines = list(difflib.unified_diff(
        before_lines, current_lines,
        fromfile=f"snapshot-before:{transaction_id[:8]}",
        tofile=f"device-current:{tx['device_id']}",
        lineterm="",
    ))
    limit = max(100, min(int(max_lines), 4000))
    truncated = len(diff_lines) > limit
    shown = diff_lines[:limit]
    additions = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removals = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))
    return {
        "success": True,
        "transaction_id": transaction_id,
        "device_id": tx["device_id"],
        "transaction_status": tx["status"],
        "added_lines": additions,
        "removed_lines": removals,
        "diff_line_count": len(diff_lines),
        "diff_truncated": truncated,
        "diff": "\n".join(shown) if shown else "(无配置差异)",
        "note": "这是文本级配置差异；不同厂商/版本的配置默认值、顺序和计数器可能变化，不能单独视为故障或变更归因结论。敏感字段已脱敏。",
    }

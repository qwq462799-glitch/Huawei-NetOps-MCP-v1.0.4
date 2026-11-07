"""Role and actor binding for stdio MCP deployments.

The principal is supplied by the protected MCP process environment, never by a
model-controlled tool argument. For multi-user deployments, give each OS account
or protected Harness profile its own NETOPS_OPERATOR_ID/ROLE configuration.
"""
from __future__ import annotations

import re

from app.config import settings

ROLE_PERMISSIONS = {
    "viewer": {"device_read", "command_read", "terminal", "diagnostics", "job_read"},
    "operator": {
        "device_read", "command_read", "terminal", "diagnostics", "job_read",
        "device_write", "change_request", "change_apply", "batch_apply",
    },
    "approver": {
        "device_read", "command_read", "terminal", "diagnostics", "job_read",
        "change_approve", "change_confirm", "change_rollback", "audit_read",
    },
    "admin": {
        "device_read", "command_read", "terminal", "diagnostics", "job_read",
        "device_write", "change_request", "change_apply", "batch_apply",
        "change_approve", "change_confirm", "change_rollback", "audit_read",
        "rbac_admin",
    },
}


def current_principal() -> dict[str, str]:
    actor = (settings.operator_id or "local-viewer").strip()
    role = (settings.operator_role or "viewer").strip().lower()
    if not actor or len(actor) > 128 or not re.fullmatch(r"[A-Za-z0-9_.@-]{1,128}", actor):
        raise PermissionError("NETOPS_OPERATOR_ID 必须为 1-128 个字母、数字或 . _ @ - 字符")
    if role not in ROLE_PERMISSIONS:
        raise PermissionError(f"无效的 NETOPS_OPERATOR_ROLE：{role}")
    return {"id": actor, "role": role}


def require_permission(permission: str) -> dict[str, str]:
    principal = current_principal()
    if permission not in ROLE_PERMISSIONS[principal["role"]]:
        raise PermissionError(
            f"当前身份 {principal['id']}（{principal['role']}）没有 {permission} 权限"
        )
    return principal


def dual_approval_required() -> bool:
    return bool(settings.require_dual_approval)

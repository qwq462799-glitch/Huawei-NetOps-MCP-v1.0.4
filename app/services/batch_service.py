"""Sequential multi-device change orchestration with preflight and compensating rollback.

A batch is deliberately not a distributed atomic transaction. All plans are
validated before the first device is touched; at runtime, the service stops on
first failure and compensates prior successful devices in reverse order.
"""
from __future__ import annotations

from app.services.device_service import (
    apply_change,
    rollback_change,
    confirm_change,
    _approval_assertions,
    _runtime_device,
    _validate_config_lists,
)
from app.drivers.factory import get_driver
from app.drivers.ssh_cli import connection_params
from app.security.command_secrets import resolve_command_secrets
from app.security.credentials import resolve_password
from app.security.redaction import redact_text
from app.security.rbac import current_principal, dual_approval_required
from app.storage import get_approval, get_device, get_transaction, audit


def _preflight_approval(approval_id: str, item: dict, principal: dict[str, str]) -> dict:
    """Validate one approved plan without opening a network connection or changing state."""
    device_id = item.get("device_id", "")
    device = get_device(device_id)
    if not device:
        raise ValueError(f"审批单 {approval_id} 对应设备 {device_id} 不存在")
    if not device.get("enabled", True):
        raise ValueError(f"审批单 {approval_id} 对应设备 {device_id} 已禁用")
    if device.get("connection") != "ssh":
        raise ValueError(f"设备 {device_id} 不是 SSH 连接；当前配置写入不支持 Telnet")

    # 双人审批在 apply 时再检查一次，避免旧数据/人工数据库修改绕过正常审批入口。
    if dual_approval_required():
        requester = item.get("requested_by")
        approver = item.get("approved_by")
        if not requester or not approver or requester == approver:
            raise PermissionError(
                f"审批单 {approval_id} 未满足双人审批：申请人和审批人必须是两个不同身份"
            )

    # 校验数据库中已保存的审批计划，而不只依赖创建时的参数校验。
    _approval_assertions(item)
    commands = resolve_command_secrets(item.get("commands") or [])
    rollback = resolve_command_secrets(item.get("rollback_commands") or [])
    _validate_config_lists(commands, rollback)

    # 解密凭证并创建 driver 对象只做本地检查，不会触发设备网络连接。
    runtime = _runtime_device(device)
    resolve_password(runtime)  # Ensure password_env/credential decryption succeeds before any device is changed.
    connection_params(runtime)  # Validate vendor/host/port/user locally; this does not open a socket.
    get_driver(runtime)
    return {"approval_id": approval_id, "device_id": device_id, "commands": len(commands)}


def apply_approved_batch(
    approval_ids: list[str],
    rollback_previous_on_failure: bool = True,
    progress=None,
) -> dict:
    if not approval_ids:
        raise ValueError("approval_ids 不能为空")
    if len(approval_ids) > 20:
        raise ValueError("单批最多允许 20 个审批单；较大变更请拆分批次")
    if len(set(approval_ids)) != len(approval_ids):
        raise ValueError("approval_ids 不能重复")

    principal = current_principal()
    approvals: list[dict] = []
    devices: set[str] = set()

    # 全量 preflight：任意审批/设备/命令计划无效时，整批不开始。
    for aid in approval_ids:
        item = get_approval(aid)
        if not item or item.get("status") != "approved":
            raise PermissionError(f"审批单 {aid} 不存在或未批准；整批未开始")
        device_id = item.get("device_id")
        if device_id in devices:
            raise ValueError(f"同一批次不能包含同一设备的多个审批单：{device_id}")
        devices.add(device_id)
        _preflight_approval(aid, item, principal)
        approvals.append(item)

    audit(principal["id"], "config.batch.preflight.success", None, {
        "approval_ids": approval_ids,
        "device_ids": [item["device_id"] for item in approvals],
        "rollback_previous_on_failure": rollback_previous_on_failure,
    })

    results = []
    successful_transactions = []
    failed = False
    for index, aid in enumerate(approval_ids, start=1):
        if progress:
            progress(int((index - 1) / len(approval_ids) * 85), f"正在执行第 {index}/{len(approval_ids)} 台设备")
        try:
            result = apply_change(aid)
        except Exception as exc:
            result = {"success": False, "status": "apply_exception", "error": redact_text(str(exc))}
        results.append({"approval_id": aid, "device_id": approvals[index - 1]["device_id"], "result": result})
        if result.get("success") and result.get("transaction_id") and result.get("status") == "pending_confirmation":
            successful_transactions.append(result["transaction_id"])
        else:
            failed = True
            break

    compensations = []
    if failed and rollback_previous_on_failure:
        for txid in reversed(successful_transactions):
            tx = get_transaction(txid)
            if tx and tx.get("status") == "pending_confirmation":
                try:
                    compensations.append(rollback_change(txid))
                except Exception as exc:
                    compensations.append({"success": False, "transaction_id": txid,
                                          "status": "rollback_exception", "error": redact_text(str(exc))})

    if progress:
        progress(100, "批量变更流程结束")

    if not failed:
        status = "pending_confirmation"
    elif not successful_transactions:
        status = "failed_no_prior_changes"
    elif not rollback_previous_on_failure:
        status = "failed_partial"
    elif all(item.get("success") and item.get("status") == "rolled_back" for item in compensations) \
            and len(compensations) == len(successful_transactions):
        status = "failed_compensated"
    else:
        status = "failed_compensation_incomplete"

    response = {
        "success": (not failed) and len(results) == len(approval_ids),
        "status": status,
        "requested_count": len(approval_ids),
        "completed_count": len(results),
        "results": results,
        "successful_transaction_ids": successful_transactions,
        "compensation_rollbacks": compensations,
        "warning": "批量变更采用逐台执行和补偿回滚，不是跨设备原子事务；补偿不完整时必须人工核查每台设备。",
    }
    audit(principal["id"], "config.batch.finished", None, {
        "status": status,
        "approval_ids": approval_ids,
        "completed_count": len(results),
        "compensation_count": len(compensations),
    })
    return response


def confirm_approved_batch(transaction_ids: list[str]) -> dict:
    """Confirm up to 20 pending transactions sequentially with per-item errors."""
    if not transaction_ids:
        raise ValueError("transaction_ids 不能为空")
    if len(transaction_ids) > 20 or len(set(transaction_ids)) != len(transaction_ids):
        raise ValueError("事务 ID 最多 20 个且不能重复")
    principal = current_principal()
    results = []
    for txid in transaction_ids:
        try:
            result = confirm_change(txid, confirmed_by=principal["id"])
        except Exception as exc:
            result = {"success": False, "transaction_id": txid,
                      "status": "confirm_exception", "error": redact_text(str(exc))}
        results.append(result)
    return {
        "success": all(item.get("success") for item in results),
        "requested_count": len(transaction_ids),
        "confirmed_count": sum(1 for item in results if item.get("success")),
        "results": results,
        "note": "确认按顺序逐笔执行，不是跨设备原子提交；失败事务需逐笔检查状态。",
    }

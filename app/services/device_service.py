from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

from app.storage import (
    get_device, list_devices, save_device, audit, create_approval, get_approval,
    approve, consume_approval_and_create_transaction, get_transaction,
    update_transaction, confirm_transaction, claim_due_rollbacks, claim_manual_rollback,
    finalize_apply_transaction, claim_interrupted_applications, complete_rollback_transaction,
)
from app.drivers.factory import get_driver
from app.security.policy import validate_command, classify_command
from app.security.credentials import encrypt_secret, decrypt_secret
from app.security.config_commands import normalize_config_commands
from app.security.device_output import detect_device_error
from app.security.redaction import redact_text
from app.security.command_secrets import (
    command_secret_values, resolve_command_secrets, redact_command_secrets,
)
from app.security.rbac import current_principal, dual_approval_required
from app.services.verification import validate_assertions, evaluate_assertions


def add_device(device: dict):
    from app.drivers.adapters.factory import normalize_device
    device = normalize_device(dict(device))
    if device["connection"] == "telnet" and device["port"] < 1:
        raise ValueError("Telnet 端口无效")
    stored = dict(device)
    if device.get("password"):
        stored["password"] = encrypt_secret(device["password"])
        stored["_password_encrypted"] = True
    elif device.get("password_env"):
        stored["password"] = None
        stored["_password_encrypted"] = False
    else:
        raise ValueError("必须提供 password 或 password_env")
    save_device(stored)
    actor = current_principal()["id"]
    audit(actor, "device.add_or_update", device["id"],
          {"name": device["name"], "vendor": device["vendor"], "host": device["host"]})
    return {"success": True, "device_id": device["id"]}


def devices():
    """Return only public device fields; never expose credential or storage metadata."""
    public_fields = {
        "id", "name", "vendor", "platform", "connection", "simulator",
        "host", "port", "username", "enabled", "environment",
    }
    return [{key: value for key, value in device.items() if key in public_fields}
            for device in list_devices()]


def _runtime_device(device):
    # 先应用模拟器适配器，再解密凭证；物理设备记录保持原样。
    from app.drivers.adapters.factory import normalize_device
    device = normalize_device(dict(device))
    if device.get("_password_encrypted"):
        device["password"] = decrypt_secret(device["password"])
    return device


def execute(device_id: str, command: str, allow_write: bool = False):
    """Run one device command and distinguish transport/tool errors from CLI errors."""
    started = time.perf_counter()
    try:
        device = get_device(device_id)
        if not device:
            raise ValueError(f"设备不存在：{device_id}")
        if not device.get("enabled", True):
            raise ValueError("设备已禁用")
        validate_command(command, allow_write=allow_write)
        runtime = _runtime_device(device)
        output = get_driver(runtime).execute(runtime, command)
        cli_error = detect_device_error(output)
        success = cli_error is None
        audit(current_principal()["id"], "command.execute", device_id, {
            "command": command, "success": success, "device_error": bool(cli_error),
            "output_length": len(output),
            "device_error_line": cli_error["line"] if cli_error else None,
        })
        result = {
            "success": success,
            "tool_success": True,
            "device_error": bool(cli_error),
            "device_id": device_id,
            "command": redact_text(command),
            "output": redact_text(output),
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
        if cli_error:
            result["error"] = "设备返回 CLI 命令错误；请检查命令是否适用于当前设备型号/系统版本。"
            result["device_error_line"] = cli_error["line"]
        return result
    except Exception as exc:
        audit(current_principal()["id"], "command.execute", device_id,
              {"command": command, "success": False, "device_error": False, "error": str(exc)})
        return {
            "success": False,
            "tool_success": False,
            "device_error": False,
            "device_id": device_id,
            "command": redact_text(command),
            "error": redact_text(str(exc)),
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }


def _snapshot_command(vendor):
    return "show running-config" if vendor == "cisco" else "display current-configuration"


def _execute_config(device, commands):
    if device.get("connection") != "ssh":
        raise RuntimeError("配置变更/回滚当前只允许 SSH；eNSP Telnet 仅开放只读操作")
    return get_driver(device).execute_config(device, commands)


def _validate_config_lists(commands: list[str], rollback_commands: list[str]) -> tuple[list[str], list[str]]:
    """Apply the exact driver normalization during approval and at execution time."""
    if len(commands) > 100 or len(rollback_commands) > 100:
        raise ValueError("单笔变更命令和回滚命令分别最多允许 100 条")
    normalized_commands = normalize_config_commands(commands)
    normalized_rollback = normalize_config_commands(rollback_commands)
    if not normalized_commands:
        raise ValueError("配置命令归一化后为空：请至少提供一条真实配置命令，不能只提交 system-view/return 等视图命令")
    if not normalized_rollback:
        raise ValueError("回滚命令归一化后为空：必须提供至少一条真实回滚命令")
    for command in normalized_commands + normalized_rollback:
        validate_command(command, allow_write=True)
        if classify_command(command) != "write":
            raise ValueError(f"变更命令和回滚命令必须是配置写命令：{command}")
    return normalized_commands, normalized_rollback


def create_change(
    device_id: str,
    commands: list[str],
    rollback_commands: list[str],
    verify_command: str,
    expected_output_contains: str = "",
    rollback_after_seconds: int = 300,
    expected_output_contains_all: list[str] | None = None,
    expected_output_not_contains: list[str] | None = None,
    expected_output_regex: list[str] | None = None,
    requested_by: str | None = None,
):
    principal = current_principal()
    requested_by = requested_by or principal["id"]
    device = get_device(device_id)
    if not device:
        raise ValueError(f"设备不存在：{device_id}")
    if not device.get("enabled", True):
        raise ValueError("设备已禁用")
    if device.get("connection") != "ssh":
        raise ValueError("配置审批仅支持 SSH 设备；传统 eNSP Telnet 当前只读")
    if not commands or not rollback_commands:
        raise ValueError("配置命令和回滚命令都必须提供；不允许创建无回滚方案的变更")

    # O-2：审批创建时即使用与 Netmiko 下发相同的归一化规则。
    normalized_commands, normalized_rollback = _validate_config_lists(commands, rollback_commands)

    if not verify_command or not verify_command.strip():
        raise ValueError("必须提供只读验证命令")
    validate_command(verify_command, allow_write=False)
    if classify_command(verify_command) != "read":
        raise ValueError("验证命令必须是只读查询命令")
    assertions = validate_assertions(
        expected_output_contains,
        expected_output_contains_all,
        expected_output_not_contains,
        expected_output_regex,
    )
    if rollback_after_seconds < 30 or rollback_after_seconds > 86400:
        raise ValueError("回滚观察窗口必须在 30 秒至 24 小时之间")

    # 存储原始命令，确保审批界面与设备下发计划一致；归一化只用于预校验。
    aid = str(uuid.uuid4())
    create_approval(
        aid, device_id, commands, rollback_commands, verify_command,
        assertions["expected_output_contains"], rollback_after_seconds,
        assertions["expected_output_contains_all"],
        assertions["expected_output_not_contains"],
        assertions["expected_output_regex"],
        requested_by=requested_by,
    )
    audit(requested_by, "approval.create", device_id, {
        "approval_id": aid,
        "commands": commands,
        "rollback_commands": rollback_commands,
        "normalized_command_count": len(normalized_commands),
        "normalized_rollback_command_count": len(normalized_rollback),
        "verify_command": verify_command,
        "verification_assertions": assertions,
        "rollback_after_seconds": rollback_after_seconds,
    })
    return {
        "approval_id": aid,
        "status": "pending",
        "commands": [redact_text(x) for x in commands],
        "rollback_commands": [redact_text(x) for x in rollback_commands],
        "verify_command": verify_command,
        **assertions,
        "rollback_after_seconds": rollback_after_seconds,
    }


def approve_change(approval_id: str, approved_by: str | None = None):
    actor = approved_by or current_principal()["id"]
    ok = approve(approval_id, approved_by=actor, require_distinct=dual_approval_required())
    item = get_approval(approval_id)
    same_actor = bool(item and item.get("requested_by") == actor and dual_approval_required())
    audit(actor, "approval.decide", item.get("device_id") if item else None,
          {"approval_id": approval_id, "approved": ok, "dual_approval": dual_approval_required()})
    return {"success": ok, "approval_id": approval_id, "approved_by": actor,
            "requested_by": item.get("requested_by") if item else None,
            "status": "approved" if ok else "same_actor_not_allowed" if same_actor else "not_pending",
            "message": "双人审批已启用，创建人与审批人必须是不同身份。" if same_actor else "审批已处理。"}


def _perform_rollback(txid: str, reason: str, actor: str = "rollback-worker"):
    tx = get_transaction(txid)
    if not tx:
        return {"success": False, "error": "变更事务不存在"}
    if tx["status"] not in ("pending_confirmation", "rolling_back"):
        return {"success": False, "status": tx["status"], "error": "事务当前状态不允许回滚"}
    device = get_device(tx["device_id"])
    if not device:
        completed = complete_rollback_transaction(txid, "rollback_failed", "设备记录不存在", actor)
        return {"success": False, "error": "设备记录不存在", "state_updated": completed}
    approval = {}
    if tx.get("approval_id"):
        try:
            approval = get_approval(tx["approval_id"]) or {}
        except Exception:
            # Optional lookup is only for output redaction; it must never block
            # an already-claimed, pre-approved rollback attempt.
            approval = {}
    secret_references = (approval.get("commands") or []) + (tx.get("rollback_commands") or [])
    # New transactions freeze resolved secret values encrypted at apply time. Old
    # databases fall back to the legacy environment placeholder resolution path.
    secret_values = tx.get("secret_values") or list(command_secret_values(secret_references).values())
    try:
        output = _execute_config(_runtime_device(device), resolve_command_secrets(tx["rollback_commands"]))
        cli_error = detect_device_error(output)
        if cli_error:
            safe_line = redact_command_secrets(cli_error["line"], secret_references, secret_values)
            raise RuntimeError(f"设备拒绝回滚命令：{safe_line}")
        safe_output = redact_command_secrets(output, secret_references, secret_values)
        completed = complete_rollback_transaction(txid, "rolled_back", safe_output, actor)
        audit(actor, "config.rollback.success" if completed else "config.rollback.state_changed", tx["device_id"],
              {"transaction_id": txid, "reason": reason, "output_length": len(output), "state_updated": completed})
        if not completed:
            return {"success": False, "transaction_id": txid, "status": "state_changed",
                    "error": "回滚执行期间事务状态已被安全恢复机制改变；请人工核查设备实际配置。",
                    "output": safe_output}
        return {"success": True, "transaction_id": txid, "status": "rolled_back", "output": safe_output}
    except Exception as exc:
        safe_error = redact_command_secrets(str(exc), secret_references, secret_values)
        completed = complete_rollback_transaction(txid, "rollback_failed", safe_error, actor)
        audit(actor, "config.rollback.failed" if completed else "config.rollback.state_changed", tx["device_id"],
              {"transaction_id": txid, "reason": reason, "error": safe_error, "state_updated": completed})
        return {"success": False, "transaction_id": txid, "status": "rollback_failed" if completed else "state_changed",
                "error": safe_error}


def _approval_assertions(item: dict) -> dict:
    """Revalidate persisted approval data before consuming the approval token."""
    _validate_config_lists(item.get("commands") or [], item.get("rollback_commands") or [])
    validate_command(item["verify_command"], allow_write=False)
    if classify_command(item["verify_command"]) != "read":
        raise ValueError("审批单中的验证命令不是只读命令")
    return validate_assertions(
        item.get("expected_output_contains", ""),
        item.get("expected_output_contains_all", []),
        item.get("expected_output_not_contains", []),
        item.get("expected_output_regex", []),
    )


def apply_change(approval_id: str, progress=None):
    progress_events: list[dict] = []

    def report(value: int, message: str):
        event = {"progress": int(value), "message": message}
        progress_events.append(event)
        if progress is not None:
            try:
                progress(value, message)
            except Exception:
                # Progress delivery must never interrupt a device change workflow.
                pass

    report(5, "正在检查审批单和设备状态")
    item = get_approval(approval_id)
    if not item or item["status"] != "approved":
        raise PermissionError("审批不存在或尚未批准")
    if dual_approval_required():
        requester = item.get("requested_by")
        approver = item.get("approved_by")
        if not requester or not approver or requester == approver:
            raise PermissionError("该审批单未满足双人审批身份要求；申请人和审批人必须不同")
    device = get_device(item["device_id"])
    if not device:
        raise ValueError("审批对应设备不存在")
    if device.get("connection") != "ssh":
        raise RuntimeError("当前版本仅允许 SSH 设备执行配置变更；eNSP Telnet 写配置暂不开放")

    # 在消耗审批单前复核持久化数据，避免无效/损坏审批占用审批令牌。
    assertions = _approval_assertions(item)
    # Resolve secret placeholders only for the live device call. Keep the
    # encrypted placeholder references in the approval/transaction database.
    secret_references = item["commands"] + item["rollback_commands"]
    resolved_secret_values = list(command_secret_values(secret_references).values())
    resolved_commands = resolve_command_secrets(item["commands"])
    resolved_rollback = resolve_command_secrets(item["rollback_commands"])
    _validate_config_lists(resolved_commands, resolved_rollback)
    runtime = _runtime_device(device)
    driver = get_driver(runtime)

    report(15, "审批有效，正在读取变更前真实配置")
    snapshot = driver.execute(runtime, _snapshot_command(device["vendor"]))
    snapshot_error = detect_device_error(snapshot)
    if snapshot_error:
        audit(current_principal()["id"], "config.apply.snapshot_failed", item["device_id"], {
            "approval_id": approval_id, "device_error_line": snapshot_error["line"]
        })
        return {
            "success": False, "status": "precheck_failed",
            "error": "读取变更前配置快照时设备返回 CLI 错误；未下发配置，审批单仍可重新处理。",
            "snapshot_output": redact_command_secrets(snapshot, secret_references, resolved_secret_values),
            "device_error_line": snapshot_error["line"],
            "progress_events": progress_events,
        }
    snapshot_encrypted = encrypt_secret(snapshot)
    report(30, "变更前配置快照已加密保存")

    txid = str(uuid.uuid4())
    apply_output = ""
    verify_output = ""
    verification = None

    # 将审批消费与 applying 事务创建放进同一个 SQLite 事务；
    # 任一步失败都整体回滚，避免出现“审批已消费但事务不存在”的孤儿状态。
    # 事务记录在第一条写命令下发之前落库，供进程崩溃恢复使用。
    if not consume_approval_and_create_transaction(
        txid, item, snapshot_encrypted, apply_output, verify_output,
        None, initial_status="applying", rollback_commands_override=resolved_rollback,
        secret_values=resolved_secret_values,
    ):
        raise PermissionError("审批已被使用或状态已变化")
    try:
        report(45, "变更事务已持久化，正在下发已批准的配置命令")
        apply_output = driver.execute_config(runtime, resolved_commands)
        apply_error = detect_device_error(apply_output)
        if apply_error:
            safe_line = redact_command_secrets(apply_error["line"], secret_references, resolved_secret_values)
            raise RuntimeError(f"设备拒绝配置命令：{safe_line}")

        report(70, "配置命令已下发，正在执行设备验证")
        verify_output = driver.execute(runtime, item["verify_command"])
        verification = evaluate_assertions(verify_output, **assertions)
        if verification.get("device_error"):
            verification["device_error"]["line"] = redact_command_secrets(
                verification["device_error"].get("line", ""), secret_references, resolved_secret_values
            )
        if not verification["passed"]:
            due = datetime.now(timezone.utc).isoformat()
            update_transaction(
                txid, "rolling_back", apply_output=redact_command_secrets(apply_output, secret_references, resolved_secret_values),
                verify_output=redact_command_secrets(verify_output, secret_references, resolved_secret_values), rollback_due_at=due,
            )
            report(85, "验证未通过，正在执行预先批准的回滚命令")
            rollback_result = _perform_rollback(txid, "post-change verification failed", actor=current_principal()["id"])
            report(100, "验证失败处理完成；请检查回滚结果")
            audit(current_principal()["id"], "config.apply.verification_failed", item["device_id"], {
                "approval_id": approval_id, "transaction_id": txid,
                "failed_checks": verification["failed_checks"],
            })
            return {
                "success": False,
                "transaction_id": txid,
                "status": "verification_failed",
                "verify_output": redact_command_secrets(verify_output, secret_references, resolved_secret_values),
                "verification": verification,
                "rollback": rollback_result,
                "progress_events": progress_events,
            }

        due = (datetime.now(timezone.utc) + timedelta(seconds=item["rollback_after_seconds"])).isoformat()
        safe_apply_output = redact_command_secrets(apply_output, secret_references, resolved_secret_values)
        safe_verify_output = redact_command_secrets(verify_output, secret_references, resolved_secret_values)
        finalized = finalize_apply_transaction(txid, safe_apply_output, safe_verify_output, due)
        if not finalized:
            raise RuntimeError("变更事务状态已变化，无法进入待确认观察窗口")
        report(100, "配置验证通过，进入回滚观察窗口；请在到期前确认变更")
        audit(current_principal()["id"], "config.apply.pending_confirmation", item["device_id"], {
            "approval_id": approval_id, "transaction_id": txid, "rollback_due_at": due,
            "snapshot_saved": True,
        })
        return {
            "success": True,
            "transaction_id": txid,
            "status": "pending_confirmation",
            "apply_output": safe_apply_output,
            "verify_output": safe_verify_output,
            "verification": verification,
            "rollback_due_at": due,
            "progress_events": progress_events,
            "message": "配置已应用并通过全部验证断言；观察窗口到期前必须调用 config_confirm_change，否则自动执行回滚命令。",
        }
    except Exception as exc:
        # 配置下发可能在设备端部分成功、但 Netmiko 未抛出可定位异常；
        # 先将预创建事务切换为 rolling_back，再执行预先批准的补偿命令。
        try:
            update_transaction(
                txid, "rolling_back", apply_output=redact_command_secrets(apply_output, secret_references, resolved_secret_values),
                verify_output=redact_command_secrets(verify_output or str(exc), secret_references, resolved_secret_values),
                rollback_due_at=datetime.now(timezone.utc).isoformat(),
            )
            report(90, "执行过程异常，正在尝试预先批准的回滚命令")
            rollback_result = _perform_rollback(txid, "apply or verification exception", actor=current_principal()["id"])
            report(100, "异常处理完成；请检查回滚结果")
        except Exception as rollback_exc:
            rollback_result = {"success": False,
                               "error": redact_command_secrets(str(rollback_exc), secret_references, resolved_secret_values)}
        audit(current_principal()["id"], "config.apply.failed", item["device_id"], {
            "approval_id": approval_id, "transaction_id": txid,
            "error": redact_command_secrets(str(exc), secret_references, resolved_secret_values), "rollback": rollback_result,
        })
        return {
            "success": False, "transaction_id": txid, "status": "apply_failed",
            "error": redact_command_secrets(str(exc), secret_references, resolved_secret_values),
            "apply_output": redact_command_secrets(apply_output, secret_references, resolved_secret_values),
            "verify_output": redact_command_secrets(verify_output, secret_references, resolved_secret_values),
            "verification": verification,
            "rollback": rollback_result, "progress_events": progress_events,
        }


def recover_interrupted_applications(age_seconds: int = 1800):
    """Recover stale `applying` transactions after the configured safety window."""
    results = []
    for txid in claim_interrupted_applications(age_seconds=age_seconds):
        result = _perform_rollback(txid, "MCP process restarted during configuration apply", actor="recovery-worker")
        audit("recovery-worker", "config.apply.interrupted_recovery",
              (get_transaction(txid) or {}).get("device_id"),
              {"transaction_id": txid, "rollback": result})
        results.append(result)
    return results



def confirm_change(transaction_id: str, confirmed_by: str | None = None):
    actor = confirmed_by or current_principal()["id"]
    ok = confirm_transaction(transaction_id, confirmed_by=actor)
    tx = get_transaction(transaction_id)
    audit(actor, "config.change.confirm", tx["device_id"] if tx else None,
          {"transaction_id": transaction_id, "confirmed": ok})
    return {"success": ok, "transaction_id": transaction_id,
            "status": "confirmed" if ok else (tx["status"] if tx else "not_found")}


def rollback_change(transaction_id: str):
    tx = get_transaction(transaction_id)
    if not tx:
        return {"success": False, "error": "事务不存在"}
    if not claim_manual_rollback(transaction_id):
        latest = get_transaction(transaction_id)
        return {
            "success": False,
            "transaction_id": transaction_id,
            "status": latest["status"] if latest else "not_found",
            "error": "事务已被确认、回滚工作线程抢占，或当前状态不允许手动回滚",
        }
    return _perform_rollback(transaction_id, "manual rollback request", actor=current_principal()["id"])


def process_due_rollbacks():
    results = []
    for txid in claim_due_rollbacks():
        results.append(_perform_rollback(txid, "confirmation deadline expired", actor="rollback-worker"))
    return results

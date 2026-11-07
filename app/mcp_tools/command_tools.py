from app.services.device_service import execute
from app.security.policy import validate_command
from app.mcp_tools._coerce import StrList
from app.security.rbac import require_permission


def execute_batch(device_id: str, commands: list[str]) -> dict:
    """Preflight a batch atomically, then stop on the first device/tool error."""
    if not commands:
        return {
            "success": False,
            "device_id": device_id,
            "requested_count": 0,
            "executed_count": 0,
            "partial_results": [],
            "rejected_commands": [],
            "stopped_reason": "empty_batch",
            "message": "命令列表为空，未执行任何命令。",
        }

    if len(commands) > 50:
        return {
            "success": False,
            "device_id": device_id,
            "requested_count": len(commands),
            "executed_count": 0,
            "partial_results": [],
            "rejected_commands": [],
            "stopped_reason": "batch_limit_exceeded",
            "message": "单次只读命令批量最多允许 50 条；未执行任何命令。",
        }

    rejected = []
    for index, command in enumerate(commands):
        try:
            validate_command(command, allow_write=False)
        except Exception as exc:
            rejected.append({"index": index, "command": command, "reason": str(exc)})

    # 安全优先：有任何策略拒绝项，整批不下发，明确返回空 partial_results。
    if rejected:
        return {
            "success": False,
            "device_id": device_id,
            "requested_count": len(commands),
            "executed_count": 0,
            "partial_results": [],
            "rejected_commands": rejected,
            "stopped_reason": "preflight_rejected",
            "message": "批量命令包含不允许的命令；为避免部分执行，本批次所有命令均未下发。",
        }

    results = []
    stopped_at = None
    stopped_reason = None
    for index, command in enumerate(commands):
        result = execute(device_id, command, allow_write=False)
        result["index"] = index
        results.append(result)
        if not result.get("success"):
            stopped_at = index
            stopped_reason = "device_cli_error" if result.get("device_error") else "tool_or_transport_error"
            break

    all_completed = len(results) == len(commands) and all(item.get("success") for item in results)
    response = {
        "success": all_completed,
        "device_id": device_id,
        "requested_count": len(commands),
        "executed_count": len(results),
        "results": results,
        "partial_results": results if not all_completed else [],
        "rejected_commands": [],
    }
    if stopped_at is not None:
        response["stopped_at_index"] = stopped_at
        response["stopped_reason"] = stopped_reason
        response["message"] = "批次已停止；partial_results 保留此前已执行命令和失败命令的原始返回。"
    return response


def register(mcp):
    @mcp.tool()
    def huawei_execute_command(device_id: str, command: str) -> dict:
        """执行单条只读命令。返回设备 CLI 错误标志与原始输出；写命令必须走审批。"""
        require_permission("command_read")
        return execute(device_id, command, allow_write=False)

    @mcp.tool()
    def huawei_execute_batch(device_id: str, commands: StrList) -> dict:
        """批量执行只读命令。先整体预检，任何写命令都会整批拒绝；设备 CLI 报错或连接异常时停止。"""
        require_permission("command_read")
        return execute_batch(device_id, commands)

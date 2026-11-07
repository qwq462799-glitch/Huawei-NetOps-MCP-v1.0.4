from __future__ import annotations

import asyncio

from fastmcp import Context

from app.mcp_tools._coerce import StrList
from app.security.rbac import require_permission, current_principal
from app.services.capabilities import COMMAND_CATALOG, fingerprint_version
from app.services.config_diff import diff_transaction
from app.services.config_templates import list_templates, render_template
from app.services.batch_service import apply_approved_batch, confirm_approved_batch
from app.services.device_service import execute
from app.storage import get_device, recent_audit


def register(mcp):
    @mcp.tool()
    def device_command_catalog(vendor: str = "") -> dict:
        """列出厂商只读诊断/巡检命令参考；仅返回建议命令，不连接设备。"""
        require_permission("device_read")
        key = vendor.strip().lower() or None
        if key and key not in COMMAND_CATALOG:
            return {"success": False, "error": "支持的厂商：huawei、h3c、cisco"}
        catalogs = {key: COMMAND_CATALOG[key]} if key else COMMAND_CATALOG
        return {"success": True, "catalogs": catalogs, "note": "命令需按设备型号和软件版本复核；实际执行仍受只读命令策略约束。"}

    @mcp.tool()
    def device_discover_capabilities(device_id: str) -> dict:
        """执行版本只读命令，识别厂商/型号线索并返回建议命令集；不会自动改设备资料。"""
        require_permission("diagnostics")
        device = get_device(device_id)
        if not device:
            return {"success": False, "error": "设备不存在", "device_id": device_id}
        vendor = device.get("vendor", "huawei")
        version_candidates = []
        if vendor in COMMAND_CATALOG:
            version_candidates.append(COMMAND_CATALOG[vendor]["version"])
        version_candidates.extend(command for command in ("display version", "show version")
                                  if command not in version_candidates)
        attempts = []
        for version_command in version_candidates:
            result = execute(device_id, version_command)
            attempts.append({"command": version_command, "success": result.get("success"),
                             "device_error": result.get("device_error"), "error": result.get("error")})
            if result.get("success"):
                fingerprint = fingerprint_version(vendor, result.get("output", ""))
                return {"success": True, "device_id": device_id, "version_command": version_command,
                        "attempts": attempts, "fingerprint": fingerprint}
        return {"success": False, "device_id": device_id, "attempts": attempts,
                "error": "所有候选版本命令均未成功，请检查设备厂商字段、CLI 平台和登录权限。"}

    @mcp.tool()
    def config_template_list(vendor: str = "") -> dict:
        """列出可审核的厂商配置模板；模板不会自动下发。"""
        require_permission("device_read")
        key = vendor.strip().lower() or None
        return {"success": True, "templates": list_templates(key)}

    @mcp.tool()
    def config_template_render(device_id: str, template_id: str, parameters: dict) -> dict:
        """按设备厂商渲染配置、回滚及验证计划；必须人工核对后另行提交审批。"""
        require_permission("change_request")
        device = get_device(device_id)
        if not device:
            return {"success": False, "error": "设备不存在", "device_id": device_id}
        return render_template(template_id, device, parameters)

    @mcp.tool()
    def config_diff_transaction(transaction_id: str, max_lines: int = 1200) -> dict:
        """将事务创建前的加密配置快照与设备当前配置作脱敏文本差异比较。"""
        require_permission("diagnostics")
        return diff_transaction(transaction_id, max_lines=max_lines)

    @mcp.tool()
    async def config_batch_apply_approved(
        ctx: Context,
        approval_ids: StrList,
        rollback_previous_on_failure: bool = True,
    ) -> dict:
        """逐台执行多个已批准变更；任一失败时可按逆序补偿回滚此前成功设备。"""
        require_permission("batch_apply")
        loop = asyncio.get_running_loop()

        def report(percent: int, message: str) -> None:
            try:
                asyncio.run_coroutine_threadsafe(ctx.report_progress(percent, 100, message), loop).result(timeout=5)
            except Exception:
                pass

        return await asyncio.to_thread(
            apply_approved_batch, approval_ids, rollback_previous_on_failure, report
        )

    @mcp.tool()
    def config_batch_confirm(transaction_ids: StrList) -> dict:
        """逐笔确认批量变更事务；这是顺序确认，不是跨设备原子提交。"""
        require_permission("change_confirm")
        try:
            return confirm_approved_batch(transaction_ids)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    @mcp.tool()
    def audit_recent(after_id: int = 0, limit: int = 100) -> dict:
        """读取增量审计记录；详情中的常见口令/密钥字段自动脱敏。"""
        require_permission("audit_read")
        return {"success": True, "events": recent_audit(after_id=after_id, limit=limit)}

    @mcp.tool()
    def netops_identity() -> dict:
        """返回当前 MCP 进程绑定的操作身份及角色（用于检查角色配置）。"""
        principal = current_principal()
        return {"success": True, **principal}

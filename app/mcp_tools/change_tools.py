import asyncio

from fastmcp import Context

from app.services.device_service import (
    create_change, approve_change, apply_change, confirm_change, rollback_change
)
from app.services.change_jobs import start_apply_job, get_apply_job
from app.mcp_tools._coerce import StrList
from app.security.rbac import require_permission


def register(mcp):
    @mcp.tool()
    def config_request_approval(
        device_id: str,
        commands: StrList,
        rollback_commands: StrList,
        verify_command: str,
        expected_output_contains: str = "",
        rollback_after_seconds: int = 300,
        expected_output_contains_all: StrList = [],
        expected_output_not_contains: StrList = [],
        expected_output_regex: StrList = [],
    ) -> dict:
        """创建配置审批单。需提供回滚命令及至少一条验证断言。

        兼容旧参数 expected_output_contains；新参数 contains_all、not_contains、regex
        支持多条 AND 断言，可用于新增和删除配置的验证。
        """
        principal = require_permission("change_request")
        return create_change(
            device_id, commands, rollback_commands, verify_command,
            expected_output_contains, rollback_after_seconds,
            expected_output_contains_all, expected_output_not_contains, expected_output_regex,
            requested_by=principal["id"],
        )

    @mcp.tool()
    def config_approve(approval_id: str) -> dict:
        """批准审批单；身份/角色绑定在 MCP 进程环境，启用双人审批时不能自批。"""
        principal = require_permission("change_approve")
        return approve_change(approval_id, approved_by=principal["id"])

    @mcp.tool()
    async def config_apply_approved(approval_id: str, ctx: Context) -> dict:
        """同步应用批准的配置；通过 MCP progress notifications 报告快照、下发、验证和回滚阶段。"""
        require_permission("change_apply")
        loop = asyncio.get_running_loop()

        def report(value: int, message: str) -> None:
            future = asyncio.run_coroutine_threadsafe(
                ctx.report_progress(value, 100, message), loop
            )
            try:
                future.result(timeout=5)
            except Exception:
                # A client without progress support must not break the operation.
                pass

        return await asyncio.to_thread(apply_change, approval_id, report)

    @mcp.tool()
    def config_apply_start(approval_id: str) -> dict:
        """异步启动已批准变更。适用于不显示 MCP progress notification 的 Harness；返回后可轮询 config_apply_progress。"""
        require_permission("change_apply")
        return start_apply_job(approval_id)

    @mcp.tool()
    def config_apply_progress(approval_id: str) -> dict:
        """查询后台变更任务的持久化阶段、事件时间线及最终执行结果。"""
        require_permission("job_read")
        return get_apply_job(approval_id)

    @mcp.tool()
    def config_confirm_change(transaction_id: str) -> dict:
        """验证业务正常后确认变更；确认后取消定时自动回滚。"""
        principal = require_permission("change_confirm")
        return confirm_change(transaction_id, confirmed_by=principal["id"])

    @mcp.tool()
    def config_rollback_now(transaction_id: str) -> dict:
        """对仍处于待确认状态的变更立即执行预先批准的回滚命令。"""
        require_permission("change_rollback")
        return rollback_change(transaction_id)

import asyncio
from fastmcp import Context

from app.services.terminal_service import (
    connect_terminal,
    disconnect_terminal,
    execute_terminal,
    list_terminal_sessions,
)
from app.services.device_service import devices
from app.security.rbac import require_permission


HELP_TEXT = """Huawei NetOps Network Terminal 命令：
  help                         显示帮助
  devices                      列出已登记设备
  connect <device_id>           连接设备并建立持久终端会话
  sessions                     查看当前终端会话
  run <session_id> :: <命令>    在指定会话执行只读 CLI 命令
  disconnect <session_id>       断开终端会话

配置写命令不会在交互终端中直接执行。请使用 config_request_approval →
config_approve → config_apply_approved；执行过程中 MCP 会报告阶段进度。
"""


def register(mcp):
    @mcp.tool()
    async def netops_terminal(command_line: str, ctx: Context) -> dict:
        """Huawei 网络设备命令行终端。支持 help/devices/connect/sessions/run/disconnect。"""
        require_permission("terminal")
        line = command_line.strip()
        if not line:
            return {"success": False, "error": "命令不能为空", "help": HELP_TEXT}
        parts = line.split(maxsplit=1)
        action = parts[0].lower()
        argument = parts[1].strip() if len(parts) > 1 else ""

        if action in ("help", "?"):
            return {"success": True, "output": HELP_TEXT}
        if action == "devices":
            return {"success": True, "devices": devices()}
        if action == "sessions":
            return {"success": True, "sessions": list_terminal_sessions()}
        if action == "connect":
            if not argument:
                return {"success": False, "error": "用法：connect <device_id>"}
            await ctx.report_progress(10, 100, "正在检查设备与连接参数")
            result = await asyncio.to_thread(connect_terminal, argument)
            await ctx.report_progress(100, 100, "终端连接完成" if result.get("success") else "终端连接失败")
            return result
        if action == "disconnect":
            if not argument:
                return {"success": False, "error": "用法：disconnect <session_id>"}
            return await asyncio.to_thread(disconnect_terminal, argument)
        if action == "run":
            if " :: " not in argument:
                return {"success": False, "error": "用法：run <session_id> :: <只读 CLI 命令>"}
            session_id, command = argument.split(" :: ", 1)
            await ctx.report_progress(5, 100, "正在检查终端会话和命令策略")
            await ctx.report_progress(25, 100, "正在向设备发送命令")
            result = await asyncio.to_thread(execute_terminal, session_id.strip(), command.strip())
            await ctx.report_progress(90, 100, "已接收设备响应，正在整理执行结果")
            await ctx.report_progress(100, 100, "命令执行完成" if result.get("success") else "命令执行失败")
            return result
        return {"success": False, "error": f"未知终端动作：{action}", "help": HELP_TEXT}

    @mcp.tool()
    async def terminal_connect(device_id: str, ctx: Context) -> dict:
        """连接网络设备并创建持久 CLI 会话，返回后续命令需要使用的 session_id。"""
        require_permission("terminal")
        await ctx.report_progress(10, 100, "检查设备信息")
        result = await asyncio.to_thread(connect_terminal, device_id)
        await ctx.report_progress(100, 100, "终端连接完成" if result.get("success") else "终端连接失败")
        return result

    @mcp.tool()
    async def terminal_execute(session_id: str, command: str, ctx: Context) -> dict:
        """在持久终端会话中执行只读 CLI 命令；配置写命令必须通过审批工具执行。"""
        require_permission("terminal")
        await ctx.report_progress(10, 100, "校验命令与会话")
        await ctx.report_progress(35, 100, "向设备发送命令")
        result = await asyncio.to_thread(execute_terminal, session_id, command)
        await ctx.report_progress(95, 100, "设备响应已接收")
        await ctx.report_progress(100, 100, "执行完成" if result.get("success") else "执行失败")
        return result

    @mcp.tool()
    def terminal_disconnect(session_id: str) -> dict:
        """断开指定持久 CLI 会话。"""
        require_permission("terminal")
        return disconnect_terminal(session_id)

    @mcp.tool()
    def terminal_sessions() -> list:
        """列出当前 MCP 进程中的终端会话。"""
        require_permission("terminal")
        return list_terminal_sessions()

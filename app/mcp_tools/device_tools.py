from app.models import Device
from app.services.device_service import add_device, devices, execute
from app.security.rbac import require_permission
from app.services.capabilities import COMMAND_CATALOG

def register(mcp):
    @mcp.tool()
    def device_add(device: dict) -> dict:
        """添加或更新设备。密码仅在服务端保存；请使用受控 MCP 客户端传入凭证。"""
        require_permission("device_write")
        obj = Device.model_validate(device)
        return add_device(obj.model_dump())

    @mcp.tool()
    def device_list() -> list:
        """列出已登记设备，不返回密码或凭证环境变量名称。"""
        require_permission("device_read")
        return devices()

    @mcp.tool()
    def device_test_connection(device_id: str) -> dict:
        """通过设备只读版本命令测试连接。"""
        require_permission("device_read")
        devs = {d["id"]: d for d in devices()}
        if device_id not in devs:
            return {"success": False, "error": "设备不存在"}
        vendor = devs[device_id]["vendor"]
        version_command = COMMAND_CATALOG.get(vendor, {}).get("version")
        if not version_command:
            return {"success": False, "error": f"暂不支持的厂商：{vendor}"}
        return execute(device_id, version_command)

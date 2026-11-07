from app.services.device_service import execute
from app.storage import get_device
from app.security.rbac import require_permission
from app.services.capabilities import COMMAND_CATALOG


_DIAGNOSTIC_KEYS = ("version", "interfaces", "routing", "vlans")
DIAGNOSTIC_COMMANDS = {
    vendor: [(key, commands[key]) for key in _DIAGNOSTIC_KEYS]
    for vendor, commands in COMMAND_CATALOG.items()
}


def register(mcp):
    @mcp.tool()
    def diagnose_device_basics(device_id: str) -> dict:
        """按厂商采集版本/接口/路由/VLAN 证据；逐条标注设备端错误，不推断故障。"""
        require_permission("diagnostics")
        device = get_device(device_id)
        if not device:
            return {"success": False, "device_id": device_id, "error": "设备不存在"}
        vendor = device.get("vendor", "huawei")
        plan = DIAGNOSTIC_COMMANDS.get(vendor)
        if not plan:
            return {"success": False, "device_id": device_id, "error": f"暂不支持 {vendor} 的诊断基线"}
        evidence = []
        for category, command in plan:
            item = execute(device_id, command)
            item["category"] = category
            evidence.append(item)
        failed = [item for item in evidence if not item.get("success")]
        return {
            "success": not failed,
            "device_id": device_id,
            "vendor": vendor,
            "evidence": evidence,
            "evidence_count": len(evidence),
            "failed_count": len(failed),
            "summary": "请根据 evidence 中的真实设备输出判断；本工具不在缺少证据时推断故障。",
        }

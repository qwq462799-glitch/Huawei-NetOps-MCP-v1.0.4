from copy import deepcopy
from app.drivers.adapters.base import SimulatorAdapter


class ENSPProAdapter(SimulatorAdapter):
    """Adapter for eNSP Pro simulated device management endpoints.

    Connects to the simulated device CLI endpoint, not the eNSP Pro web/API
    management endpoint. SSH is preferred; Telnet is permitted only when the
    specific image/device exposes it and the operator explicitly configures it.
    """
    name = "ensp_pro"

    def normalize(self, device: dict) -> dict:
        item = deepcopy(device)
        if item.get("vendor") != "huawei":
            raise ValueError("eNSP Pro 适配器当前仅支持 Huawei VRP 模拟设备")
        item.setdefault("platform", "huawei_vrp")
        item.setdefault("connection", "ssh")
        if item["connection"] not in ("ssh", "telnet"):
            raise ValueError("eNSP Pro 设备连接方式必须是 SSH 或 Telnet")
        if not item.get("host") or not item.get("port"):
            raise ValueError("必须填写 eNSP Pro 模拟设备 CLI 的可达 IP 和端口，不能填写平台 Web 管理地址")
        item["simulator"] = self.name
        return item

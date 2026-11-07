from copy import deepcopy
from app.drivers.adapters.base import SimulatorAdapter


class ENSPLegacyAdapter(SimulatorAdapter):
    """Adapter for classic Huawei eNSP device console endpoints.

    Classic eNSP commonly exposes per-node Telnet console ports. The actual
    host/port must be taken from the user's topology; no port is guessed here.
    """
    name = "ensp"

    def normalize(self, device: dict) -> dict:
        item = deepcopy(device)
        if item.get("vendor") != "huawei":
            raise ValueError("传统 eNSP 适配器当前仅支持 Huawei VRP 模拟设备")
        item.setdefault("platform", "huawei_vrp")
        item.setdefault("connection", "telnet")
        if item["connection"] not in ("telnet", "ssh"):
            raise ValueError("传统 eNSP 仅支持配置为 SSH 或 Telnet 的设备连接")
        if not item.get("host") or not item.get("port"):
            raise ValueError("传统 eNSP 必须填写该模拟节点实际可达的 Console host/port")
        item["simulator"] = self.name
        return item

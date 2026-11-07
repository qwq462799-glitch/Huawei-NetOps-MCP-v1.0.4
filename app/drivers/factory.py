from app.drivers.ssh_cli import SSHCLIDriver
from app.drivers.telnet_cli import TelnetCLIDriver
from app.drivers.adapters.factory import normalize_device


def get_driver(device: dict):
    """Resolve simulator profile first, then select the shared CLI transport."""
    normalized = normalize_device(device)
    kind = normalized.get("connection", "ssh").lower()
    if kind == "ssh":
        return SSHCLIDriver()
    if kind == "telnet":
        return TelnetCLIDriver()
    raise ValueError(f"暂不支持的连接方式：{kind}")

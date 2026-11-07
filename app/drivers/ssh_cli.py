from app.drivers.base import NetworkDriver
from app.security.credentials import resolve_password

DEVICE_TYPES = {
    "huawei": "huawei",
    "h3c": "hp_comware",
    "cisco": "cisco_ios",
}


def _netmiko_device_type(device: dict) -> str | None:
    vendor = device.get("vendor")
    platform = str(device.get("platform", "")).lower()
    if vendor == "cisco" and ("nxos" in platform or "nexus" in platform):
        return "cisco_nxos"
    return DEVICE_TYPES.get(vendor)

# 审批预校验和 Netmiko 下发共用同一套命令归一化规则。
from app.security.config_commands import normalize_config_commands


def connection_params(device: dict) -> dict:
    dtype = _netmiko_device_type(device)
    if not dtype:
        raise ValueError(f"不支持的厂商：{device['vendor']}")
    return {
        "device_type": dtype,
        "host": device["host"],
        "port": int(device.get("port", 22)),
        "username": device["username"],
        "password": resolve_password(device),
        "timeout": 15,
        "conn_timeout": 10,
        "auth_timeout": 15,
        "banner_timeout": 15,
        "fast_cli": False,
    }


class SSHInteractiveSession:
    """持久 Netmiko SSH 会话。调用方必须先执行只读策略校验。"""
    def __init__(self, connection):
        self.connection = connection

    def execute_read(self, command: str) -> str:
        # timing 模式能处理部分设备的动态提示符/分页；不提供任意交互 shell。
        output = self.connection.send_command_timing(
            command, strip_prompt=True, strip_command=True,
            read_timeout=30, last_read=1.0
        )
        return output

    def close(self):
        self.connection.disconnect()


class SSHCLIDriver(NetworkDriver):
    def open_interactive_session(self, device: dict) -> SSHInteractiveSession:
        # 延迟导入：纯策略/界面测试不需要初始化 Netmiko。
        from netmiko import ConnectHandler
        # Harness terminal session keeps this SSH connection alive between MCP tool calls.
        return SSHInteractiveSession(ConnectHandler(**connection_params(device)))

    def execute(self, device: dict, command: str) -> str:
        from netmiko import ConnectHandler
        with ConnectHandler(**connection_params(device)) as conn:
            return conn.send_command(command, read_timeout=30, strip_prompt=True, strip_command=True)

    def execute_config(self, device: dict, commands: list[str]) -> str:
        """在同一 SSH 会话中下发配置命令，避免每条命令重新连接导致配置视图丢失。"""
        normalized = normalize_config_commands(commands)
        if not normalized:
            raise ValueError("配置命令列表为空：剥离视图命令后没有可下发的命令")
        # 空列表校验必须早于 Netmiko 导入/建连，确保审批阶段的 no-op 用例
        # 不会因本地未安装可选驱动而产生误导性连接错误。
        from netmiko import ConnectHandler
        with ConnectHandler(**connection_params(device)) as conn:
            return conn.send_config_set(normalized, read_timeout=60)

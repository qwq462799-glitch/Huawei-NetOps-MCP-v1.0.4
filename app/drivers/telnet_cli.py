import time
from app.drivers.base import NetworkDriver
from app.security.credentials import resolve_password


class TelnetInteractiveSession:
    """eNSP Telnet 持久会话；依赖实验环境常见的 VRP 登录提示交互。"""
    def __init__(self, device: dict):
        self.device = device
        self.timeout = int(device.get("timeout", 10))
        # Python 3.13 移除了标准库 telnetlib；仅在真正使用 Telnet 时导入。
        try:
            import telnetlib
        except ImportError as exc:
            raise RuntimeError("当前 Python 版本已移除 telnetlib；请使用 Python 3.12 或为此驱动迁移 telnetlib3") from exc
        self.tn = telnetlib.Telnet(device["host"], int(device["port"]), timeout=self.timeout)
        self._login()

    def _read(self, delay: float = 0.3) -> str:
        time.sleep(delay)
        return self.tn.read_very_eager().decode(errors="ignore")

    def _login(self):
        user = self.device.get("username", "")
        password = resolve_password(self.device)
        self.tn.write(b"\n")
        data = self._read(0.4).lower()
        if "username" in data or "login:" in data:
            self.tn.write(user.encode() + b"\n")
            data = self._read(0.3).lower()
        if "password" in data:
            self.tn.write(password.encode() + b"\n")
            data = self._read(0.6).lower()
        self.tn.write(b"screen-length 0 temporary\n")
        self._read(0.2)

    def execute_read(self, command: str) -> str:
        self.tn.write(command.encode() + b"\n")
        return self._read(float(self.device.get("command_delay", 1.0)))

    def close(self):
        self.tn.close()


class TelnetCLIDriver(NetworkDriver):
    """eNSP Console/Telnet 驱动。认证提示符可能因镜像版本不同而需调整。"""
    def open_interactive_session(self, device: dict) -> TelnetInteractiveSession:
        return TelnetInteractiveSession(device)

    def execute(self, device: dict, command: str) -> str:
        session = self.open_interactive_session(device)
        try:
            return session.execute_read(command)
        finally:
            session.close()

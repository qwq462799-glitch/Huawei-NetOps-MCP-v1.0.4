from app.services import terminal_service as service


class FakeConnection:
    def __init__(self):
        self.commands = []
        self.closed = False

    def execute_read(self, command):
        self.commands.append(command)
        return f"DEVICE-OUTPUT::{command}"

    def close(self):
        self.closed = True


class FakeDriver:
    def __init__(self, connection):
        self.connection = connection

    def open_interactive_session(self, _device):
        return self.connection


def setup_fake(monkeypatch):
    service.close_all_terminal_sessions()
    fake = FakeConnection()
    monkeypatch.setattr(service, "get_device", lambda _device_id: {
        "id": "r1", "name": "R1", "vendor": "huawei", "platform": "huawei_vrp",
        "connection": "ssh", "host": "192.0.2.1", "port": 22,
        "username": "netops", "password": "ciphertext", "enabled": True,
    })
    monkeypatch.setattr(service, "_runtime_device", lambda device: device)
    monkeypatch.setattr(service, "get_driver", lambda _device: FakeDriver(fake))
    monkeypatch.setattr(service, "audit", lambda *args, **kwargs: None)
    return fake


def test_terminal_session_persists_between_commands(monkeypatch):
    fake = setup_fake(monkeypatch)
    opened = service.connect_terminal("r1")
    assert opened["success"] is True
    sid = opened["session_id"]

    first = service.execute_terminal(sid, "display version")
    second = service.execute_terminal(sid, "display interface brief")

    assert first["output"] == "DEVICE-OUTPUT::display version"
    assert second["output"] == "DEVICE-OUTPUT::display interface brief"
    assert fake.commands == ["display version", "display interface brief"]
    assert len(service.list_terminal_sessions()) == 1

    closed = service.disconnect_terminal(sid)
    assert closed["success"] is True
    assert fake.closed is True
    assert service.list_terminal_sessions() == []


def test_terminal_session_rejects_writes_and_dangerous_commands(monkeypatch):
    fake = setup_fake(monkeypatch)
    opened = service.connect_terminal("r1")
    sid = opened["session_id"]

    write_result = service.execute_terminal(sid, "system-view")
    dangerous_result = service.execute_terminal(sid, "reboot")

    assert write_result["success"] is False
    assert "审批" in write_result["next_step"]
    assert dangerous_result["success"] is False
    assert fake.commands == []
    service.disconnect_terminal(sid)


def test_unknown_terminal_session_returns_actionable_error(monkeypatch):
    service.close_all_terminal_sessions()
    result = service.execute_terminal("not-found", "display version")
    assert result["success"] is False
    assert "重新 connect" in result["error"]


def test_terminal_marks_device_parser_error_separately(monkeypatch):
    fake = setup_fake(monkeypatch)
    opened = service.connect_terminal("r1")
    sid = opened["session_id"]
    fake.execute_read = lambda command: "Error: Unrecognized command found at '^' position."

    result = service.execute_terminal(sid, "display hostname")
    assert result["success"] is False
    assert result["tool_success"] is True
    assert result["device_error"] is True
    assert "Unrecognized command" in result["output"]
    service.disconnect_terminal(sid)


def test_terminal_connection_error_is_redacted(monkeypatch):
    service.close_all_terminal_sessions()
    monkeypatch.setattr(service, "get_device", lambda _device_id: {
        "id": "r1", "name": "R1", "vendor": "huawei", "platform": "huawei_vrp",
        "connection": "ssh", "host": "192.0.2.1", "port": 22,
        "username": "netops", "password": "ciphertext", "enabled": True,
    })
    monkeypatch.setattr(service, "_runtime_device", lambda device: device)
    class BrokenDriver:
        def open_interactive_session(self, _device):
            raise RuntimeError("password cipher TerminalSecret123")
    monkeypatch.setattr(service, "get_driver", lambda _device: BrokenDriver())
    monkeypatch.setattr(service, "audit", lambda *args, **kwargs: None)
    result = service.connect_terminal("r1")
    assert result["success"] is False
    assert "TerminalSecret123" not in result["error"]
    assert "<REDACTED>" in result["error"]


def test_terminal_session_limits_are_enforced(monkeypatch):
    fake = setup_fake(monkeypatch)
    monkeypatch.setattr(service, "MAX_SESSIONS_PER_DEVICE", 1)
    first = service.connect_terminal("r1")
    assert first["success"] is True
    second = service.connect_terminal("r1")
    assert second["success"] is False
    assert "最多允许 1 个" in second["error"]
    assert len(service.list_terminal_sessions()) == 1
    service.disconnect_terminal(first["session_id"])

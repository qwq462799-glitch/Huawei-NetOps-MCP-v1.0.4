from app.services import device_service


class FakeDriver:
    def __init__(self, output):
        self.output = output

    def execute(self, _device, _command):
        return self.output


def test_execute_distinguishes_device_cli_error_from_transport_error(monkeypatch):
    monkeypatch.setattr(device_service, "get_device", lambda _id: {
        "id": "sw1", "vendor": "huawei", "connection": "ssh", "enabled": True,
    })
    monkeypatch.setattr(device_service, "_runtime_device", lambda device: device)
    monkeypatch.setattr(device_service, "get_driver", lambda _device: FakeDriver(
        "Error: Unrecognized command found at '^' position."
    ))
    monkeypatch.setattr(device_service, "audit", lambda *args, **kwargs: None)

    result = device_service.execute("sw1", "display hostname")
    assert result["success"] is False
    assert result["tool_success"] is True
    assert result["device_error"] is True
    assert "Unrecognized command" in result["output"]


def test_execute_policy_rejection_is_not_a_device_error(monkeypatch):
    monkeypatch.setattr(device_service, "get_device", lambda _id: {
        "id": "sw1", "vendor": "huawei", "connection": "ssh", "enabled": True,
    })
    monkeypatch.setattr(device_service, "audit", lambda *args, **kwargs: None)
    result = device_service.execute("sw1", "system-view")
    assert result["success"] is False
    assert result["tool_success"] is False
    assert result["device_error"] is False
    assert "审批" in result["error"]


def test_device_list_omits_internal_credential_metadata(monkeypatch):
    monkeypatch.setattr(device_service, "list_devices", lambda: [{
        "id": "sw1", "name": "SW1", "vendor": "huawei", "host": "192.0.2.1",
        "password": "ciphertext", "password_env": "SW1_PASSWORD",
        "_password_encrypted": True, "internal_debug": "do-not-expose",
    }])
    result = device_service.devices()
    assert result == [{
        "id": "sw1", "name": "SW1", "vendor": "huawei", "host": "192.0.2.1",
    }]

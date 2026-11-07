import pytest
from app.services import device_service


def setup_service(monkeypatch):
    captured = {}
    monkeypatch.setattr(device_service, "get_device", lambda _id: {
        "id": "sw1", "vendor": "huawei", "connection": "ssh", "enabled": True,
    })
    def capture(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
    monkeypatch.setattr(device_service, "create_approval", capture)
    monkeypatch.setattr(device_service, "audit", lambda *args, **kwargs: None)
    return captured


def test_view_only_config_plan_is_rejected_before_approval_creation(monkeypatch):
    captured = setup_service(monkeypatch)
    with pytest.raises(ValueError, match="归一化后为空"):
        device_service.create_change(
            "sw1", ["system-view", "return"], ["system-view", "return"],
            "display vlan", "VLAN", 300,
        )
    assert "args" not in captured


def test_delete_verification_assertions_can_be_created(monkeypatch):
    captured = setup_service(monkeypatch)
    result = device_service.create_change(
        "sw1",
        ["system-view", "undo vlan 400", "commit", "return"],
        ["system-view", "vlan 400", "commit", "return"],
        "display vlan",
        "",
        300,
        ["VLAN"],
        ["VLAN 400"],
        [r"VLAN\s+\d+"],
    )
    assert result["status"] == "pending"
    assert result["expected_output_not_contains"] == ["VLAN 400"]
    assert result["expected_output_regex"] == [r"VLAN\s+\d+"]
    assert captured["args"][7:10] == (["VLAN"], ["VLAN 400"], [r"VLAN\s+\d+"])
    assert captured["kwargs"]["requested_by"] == "local-viewer"


def test_telnet_device_cannot_create_write_approval(monkeypatch):
    captured = setup_service(monkeypatch)
    monkeypatch.setattr(device_service, "get_device", lambda _id: {
        "id": "r1", "vendor": "huawei", "connection": "telnet", "enabled": True,
    })
    with pytest.raises(ValueError, match="仅支持 SSH"):
        device_service.create_change(
            "r1", ["vlan 100"], ["undo vlan 100"], "display vlan", "VLAN", 300,
        )
    assert "args" not in captured

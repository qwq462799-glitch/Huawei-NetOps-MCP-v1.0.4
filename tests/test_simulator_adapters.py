import pytest

from app.drivers.adapters.factory import normalize_device


def _device(**overrides):
    item = {
        "id": "r1", "name": "Router", "vendor": "huawei",
        "platform": "huawei_vrp", "host": "192.0.2.10",
        "port": 22, "username": "netops", "connection": "ssh",
    }
    item.update(overrides)
    return item


def test_legacy_ensp_defaults_to_telnet():
    raw = _device(simulator="ensp")
    raw.pop("connection")
    item = normalize_device(raw)
    assert item["connection"] == "telnet"
    assert item["simulator"] == "ensp"


def test_ensp_pro_defaults_to_ssh():
    item = _device(simulator="ensp_pro")
    item.pop("connection")
    normalized = normalize_device(item)
    assert normalized["connection"] == "ssh"
    assert normalized["simulator"] == "ensp_pro"


def test_ensp_pro_rejects_non_huawei_vendor():
    with pytest.raises(ValueError, match="Huawei"):
        normalize_device(_device(simulator="ensp_pro", vendor="cisco"))


def test_simulator_requires_cli_host_and_port():
    with pytest.raises(ValueError, match="CLI"):
        normalize_device(_device(simulator="ensp_pro", host=""))


def test_physical_device_is_unchanged():
    item = _device()
    assert normalize_device(item) == item


def test_unknown_simulator_is_rejected():
    with pytest.raises(ValueError, match="未知模拟器"):
        normalize_device(_device(simulator="other"))

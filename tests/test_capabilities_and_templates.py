import pytest
from app.services.capabilities import fingerprint_version
from app.services.config_templates import list_templates
from app.services.config_templates import render_template


def test_fingerprint_detects_yunshan_cloudengine_and_ce_model():
    result = fingerprint_version("huawei", "Huawei YunShan OS\nCE6800 V300R025C10SPC500")
    assert result["detected_vendor"] == "huawei"
    assert result["platform_hint"] == "huawei_vrp8_or_cloudengine"
    assert result["model_hint"] == "CE6800"


def test_fingerprint_identifies_cisco_iosxe():
    result = fingerprint_version("huawei", "Cisco IOS XE Software, Version 17.9.4")
    assert result["detected_vendor"] == "cisco"
    assert result["vendor_matches_configuration"] is False


def test_template_catalog_is_vendor_scoped():
    assert all(item["vendor"] == "cisco" for item in list_templates("cisco"))


def test_huawei_vlan_template_returns_approval_plan_but_does_not_apply():
    device = {"id": "sw1", "vendor": "huawei", "platform": "huawei_vrp8"}
    plan = render_template("huawei_vlan_create", device, {"vlan_id": 300, "description": "LAB VLAN", "commit": True})
    assert plan["commands"] == ["system-view", "vlan 300", "description LAB VLAN", "commit", "return"]
    assert plan["rollback_commands"] == ["system-view", "undo vlan 300", "commit", "return"]
    assert plan["requires_manual_review"] is True


def test_template_rejects_command_injection_in_description():
    with pytest.raises(ValueError, match="仅允许"):
        render_template("huawei_vlan_create", {"id": "sw1", "vendor": "huawei"},
                        {"vlan_id": 300, "description": "ok; reboot"})


def test_template_rejects_vendor_mismatch():
    with pytest.raises(ValueError, match="模板厂商"):
        render_template("huawei_vlan_create", {"id": "r1", "vendor": "cisco"}, {"vlan_id": 10})


def test_static_route_template_normalizes_network_and_validates_hop():
    plan = render_template("cisco_static_route_add", {"id": "r1", "vendor": "cisco"},
                           {"prefix": "10.1.2.9/24", "next_hop": "192.0.2.1"})
    assert "ip route 10.1.2.0 255.255.255.0 192.0.2.1 1" in plan["commands"]
    with pytest.raises(ValueError, match="有效 IPv4 地址"):
        render_template("cisco_static_route_add", {"id": "r1", "vendor": "cisco"},
                        {"prefix": "10.0.0.0/24", "next_hop": "not-an-ip"})


def test_cisco_nxos_platform_uses_nxos_netmiko_driver_type():
    from app.drivers.ssh_cli import _netmiko_device_type
    assert _netmiko_device_type({"vendor": "cisco", "platform": "cisco_nxos"}) == "cisco_nxos"
    assert _netmiko_device_type({"vendor": "cisco", "platform": "cisco_iosxe"}) == "cisco_ios"


def test_vendor_static_route_templates_render_native_network_and_mask_length():
    from app.services.config_templates import render_template
    huawei = render_template("huawei_static_route_add", {"id": "r1", "vendor": "huawei"},
                             {"prefix": "192.0.2.0/24", "next_hop": "192.0.2.1"})
    h3c = render_template("h3c_static_route_add", {"id": "r2", "vendor": "h3c"},
                          {"prefix": "198.51.100.0/25", "next_hop": "198.51.100.1"})
    assert "ip route-static 192.0.2.0 24 192.0.2.1 preference 60" in huawei["commands"]
    assert "ip route-static 198.51.100.0 25 198.51.100.1 preference 60" in h3c["commands"]


def test_static_route_template_rejects_decimal_preference_or_distance():
    from app.services.config_templates import render_template
    with pytest.raises(ValueError):
        render_template("huawei_static_route_add", {"id": "r1", "vendor": "huawei"},
                        {"prefix": "192.0.2.0/24", "next_hop": "192.0.2.1", "preference": 60.5})
    with pytest.raises(ValueError):
        render_template("cisco_static_route_add", {"id": "r1", "vendor": "cisco"},
                        {"prefix": "192.0.2.0/24", "next_hop": "192.0.2.1", "distance": True})

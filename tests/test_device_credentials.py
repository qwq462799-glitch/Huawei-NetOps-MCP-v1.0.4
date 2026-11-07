import pytest
from app.models import Device


def base_device():
    return {
        "id": "r1", "name": "R1", "vendor": "huawei", "platform": "huawei_vrp",
        "host": "192.0.2.1", "port": 22, "username": "netops",
    }


def test_device_accepts_password_value():
    device = Device(**base_device(), password="lab-password")
    assert device.password == "lab-password"
    assert device.password_env is None


def test_device_accepts_password_environment_variable():
    device = Device(**base_device(), password_env="R1_PASSWORD")
    assert device.password is None
    assert device.password_env == "R1_PASSWORD"


def test_device_rejects_missing_or_ambiguous_password_source():
    with pytest.raises(ValueError):
        Device(**base_device())
    with pytest.raises(ValueError):
        Device(**base_device(), password="pw", password_env="R1_PASSWORD")


def test_device_password_env_can_be_loaded_from_project_dotenv(tmp_path, monkeypatch):
    from app.security import credentials
    monkeypatch.setattr(credentials, "PROJECT_ENV_FILE", tmp_path / ".env")
    monkeypatch.delenv("LAB_SWITCH_PASSWORD", raising=False)
    (tmp_path / ".env").write_text("LAB_SWITCH_PASSWORD=LabOnlySecret123\n", encoding="utf-8")
    assert credentials.resolve_password({"password_env": "LAB_SWITCH_PASSWORD"}) == "LabOnlySecret123"


def test_device_rejects_invalid_port_and_command_delimiter_in_host():
    with pytest.raises(ValueError):
        Device(**{**base_device(), "port": 70000}, password="pw")
    with pytest.raises(ValueError):
        Device(**{**base_device(), "host": "192.0.2.1;reboot"}, password="pw")
    with pytest.raises(ValueError):
        Device(**{**base_device(), "host": "192.0.2.1 attacker"}, password="pw")


def test_device_rejects_invalid_password_environment_name_and_multiline_password():
    with pytest.raises(ValueError):
        Device(**base_device(), password_env="BAD-NAME")
    with pytest.raises(ValueError):
        Device(**base_device(), password="line1\nline2")


def test_device_accepts_ipv6_host_and_normal_integer_string_port():
    device = Device(**{**base_device(), "host": "2001:db8::1", "port": "2222"}, password="lab-password")
    assert device.host == "2001:db8::1"
    assert device.port == 2222


def test_classic_ensp_defaults_to_telnet_when_connection_is_omitted():
    device = Device(
        **{**base_device(), "simulator": "ensp", "port": 2001},
        password_env="R1_PASSWORD",
    )
    assert device.connection == "telnet"


def test_ensp_pro_and_physical_devices_default_to_ssh():
    pro = Device(
        **{**base_device(), "simulator": "ensp_pro"},
        password_env="R1_PASSWORD",
    )
    physical = Device(**base_device(), password_env="R1_PASSWORD")
    assert pro.connection == "ssh"
    assert physical.connection == "ssh"

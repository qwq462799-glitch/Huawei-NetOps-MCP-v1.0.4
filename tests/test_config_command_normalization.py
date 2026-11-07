"""配置命令视图归一化与下发行为的回归测试。"""
import sys
import types

import pytest

from app.drivers import ssh_cli
from app.drivers.ssh_cli import SSHCLIDriver
from app.security.config_commands import normalize_config_commands


def test_strips_leading_system_view_and_trailing_return():
    assert normalize_config_commands(
        ["system-view", "vlan 100", "description NETOPS-TEST", "commit", "return"]
    ) == ["vlan 100", "description NETOPS-TEST", "commit"]


def test_keeps_interior_quit_for_view_navigation():
    assert normalize_config_commands(
        ["system-view", "interface GE0/0/1", "description uplink", "quit", "vlan 100", "return"]
    ) == ["interface GE0/0/1", "description uplink", "quit", "vlan 100"]


def test_case_insensitive_and_whitespace_trimmed():
    assert normalize_config_commands(
        ["  SYSTEM-VIEW  ", " Vlan 200 ", " Commit ", " RETURN "]
    ) == ["Vlan 200", "Commit"]


def test_blank_commands_are_dropped():
    assert normalize_config_commands(["", "   ", "system-view", "vlan 300", "", "return"]) == [
        "vlan 300",
    ]


def test_only_view_commands_normalize_to_empty():
    assert normalize_config_commands(["system-view", "return"]) == []


def test_trailing_exit_variants_are_stripped():
    for exit_command in ("return", "end", "exit", "quit", "QUIT"):
        assert normalize_config_commands(["vlan 100", exit_command]) == ["vlan 100"]


def test_execute_config_sends_normalized_commands_to_netmiko(monkeypatch):
    recorded = {}

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def send_config_set(self, commands, read_timeout=60):
            recorded["commands"] = list(commands)
            recorded["read_timeout"] = read_timeout
            return "CONFIG-OK"

    fake_netmiko = types.SimpleNamespace(ConnectHandler=lambda **kwargs: FakeConnection())
    monkeypatch.setitem(sys.modules, "netmiko", fake_netmiko)
    monkeypatch.setattr(ssh_cli, "connection_params", lambda device: {})

    driver = SSHCLIDriver()
    output = driver.execute_config(
        {"vendor": "huawei", "host": "192.0.2.1", "username": "n", "password": "p"},
        ["system-view", "vlan 100", "description NETOPS-TEST", "commit", "return"],
    )

    assert output == "CONFIG-OK"
    assert recorded["commands"] == ["vlan 100", "description NETOPS-TEST", "commit"]
    assert recorded["read_timeout"] == 60


def test_execute_config_rejects_empty_normalized_list(monkeypatch):
    monkeypatch.setattr(ssh_cli, "connection_params", lambda device: {})
    driver = SSHCLIDriver()
    with pytest.raises(ValueError, match="配置命令列表为空"):
        driver.execute_config({"vendor": "huawei"}, ["system-view", "return"])

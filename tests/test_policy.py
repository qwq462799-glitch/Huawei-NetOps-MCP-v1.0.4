import pytest
from app.security.policy import classify_command, validate_command

def test_read_command_allowed():
    assert validate_command("display version") == "read"

def test_write_command_blocked_by_default():
    with pytest.raises(PermissionError):
        validate_command("system-view")

def test_dangerous_command_denied_even_with_write():
    with pytest.raises(ValueError):
        validate_command("reboot", allow_write=True)

def test_write_command_can_be_classified_for_approval():
    assert classify_command("vlan 100") == "write"


def test_undo_shutdown_allowed_for_approved_rollback():
    # 恢复接口时常见的 undo shutdown 应允许进入审批回滚流程。
    assert validate_command("undo shutdown", allow_write=True) == "write"


def test_read_only_filter_can_search_for_high_risk_words():
    # 这里的 shutdown 是被查询的配置文本，而不是准备执行的 shutdown 命令。
    assert validate_command("display current-configuration | include shutdown") == "read"


def test_multicommand_injection_is_rejected_even_with_read_only_prefix():
    with pytest.raises(ValueError):
        validate_command("display clock; reboot")


def test_read_only_pipe_filter_allowlist():
    assert validate_command("show running-config | include hostname") == "read"
    assert validate_command("display current-configuration | exclude shutdown") == "read"
    assert validate_command("show interfaces | section GigabitEthernet") == "read"


@pytest.mark.parametrize("command", [
    "show running-config | redirect flash:backup.cfg",
    "show running-config | tee backup.cfg",
    "display current-configuration | save flash:/config.txt",
    "show running-config | execute script.tcl",
    "show running-config | include hostname | include version",
    "show running-config > backup.cfg",
])
def test_read_only_policy_rejects_pipe_redirection_and_chaining(command):
    with pytest.raises((ValueError, PermissionError)):
        validate_command(command, allow_write=False)


def test_cisco_no_shutdown_is_allowed_only_through_approval():
    assert validate_command("no shutdown", allow_write=True) == "write"
    with pytest.raises(PermissionError):
        validate_command("no shutdown", allow_write=False)
    with pytest.raises(ValueError):
        validate_command("shutdown", allow_write=True)

import pytest
from app.security.policy import classify_command, validate_command


def test_terminal_read_commands_are_allowed():
    assert classify_command("display version") == "read"
    assert validate_command("show running-config", allow_write=False) == "read"


def test_terminal_write_commands_are_not_read_only():
    assert classify_command("system-view") == "write"
    with pytest.raises(PermissionError):
        validate_command("system-view", allow_write=False)


def test_terminal_dangerous_commands_are_denied():
    with pytest.raises(ValueError):
        validate_command("reboot", allow_write=False)

from app.mcp_tools import command_tools


def test_batch_preflight_rejects_entire_batch_without_execution(monkeypatch):
    called = []
    monkeypatch.setattr(command_tools, "execute", lambda *a, **k: called.append(a))
    result = command_tools.execute_batch("sw1", ["display clock", "system-view", "display version"])
    assert result["success"] is False
    assert result["executed_count"] == 0
    assert result["partial_results"] == []
    assert result["rejected_commands"][0]["index"] == 1
    assert called == []


def test_batch_stops_on_device_cli_error_and_returns_partial_results(monkeypatch):
    outcomes = [
        {"success": True, "device_error": False, "output": "clock"},
        {"success": False, "device_error": True, "output": "Error: Unrecognized command"},
        {"success": True, "device_error": False, "output": "version"},
    ]
    calls = []

    def fake_execute(_device_id, _command, allow_write=False):
        calls.append(_command)
        return outcomes[len(calls) - 1]

    monkeypatch.setattr(command_tools, "execute", fake_execute)
    result = command_tools.execute_batch("sw1", ["display clock", "display hostname", "display version"])
    assert result["success"] is False
    assert result["executed_count"] == 2
    assert result["stopped_at_index"] == 1
    assert result["stopped_reason"] == "device_cli_error"
    assert len(result["partial_results"]) == 2
    assert calls == ["display clock", "display hostname"]


def test_empty_batch_is_not_reported_as_success():
    result = command_tools.execute_batch("sw1", [])
    assert result["success"] is False
    assert result["stopped_reason"] == "empty_batch"


def test_semicolon_and_multiline_command_are_not_accepted_by_read_policy():
    from app.security.policy import validate_command
    import pytest

    with pytest.raises(ValueError, match="换行"):
        validate_command("display clock\nsystem-view")
    with pytest.raises(ValueError, match="分号"):
        validate_command("display clock;system-view")


def test_read_command_batch_limit_rejects_before_execution(monkeypatch):
    from app.mcp_tools import command_tools
    monkeypatch.setattr(command_tools, "execute", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not execute")))
    result = command_tools.execute_batch("sw1", ["display clock"] * 51)
    assert result["success"] is False
    assert result["stopped_reason"] == "batch_limit_exceeded"
    assert result["executed_count"] == 0

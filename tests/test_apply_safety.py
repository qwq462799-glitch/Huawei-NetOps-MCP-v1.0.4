from app.services import device_service


class FakeDriver:
    def __init__(self, snapshot, apply_output="", verify_output="VLAN 300"):
        self.snapshot = snapshot
        self.apply_output = apply_output
        self.verify_output = verify_output

    def execute(self, _device, command):
        if command == "display current-configuration":
            return self.snapshot
        return self.verify_output

    def execute_config(self, _device, _commands):
        return self.apply_output


def _approval():
    return {
        "id": "approval-1", "device_id": "sw1", "status": "approved",
        "requested_by": "alice", "approved_by": "bob",
        "commands": ["system-view", "vlan 300", "commit", "return"],
        "rollback_commands": ["system-view", "undo vlan 300", "commit", "return"],
        "verify_command": "display vlan 300", "expected_output_contains": "VLAN 300",
        "expected_output_contains_all": [], "expected_output_not_contains": [],
        "expected_output_regex": [], "rollback_after_seconds": 300,
    }


def _base(monkeypatch, driver):
    monkeypatch.setattr(device_service, "get_approval", lambda _id: _approval())
    monkeypatch.setattr(device_service, "get_device", lambda _id: {
        "id": "sw1", "vendor": "huawei", "connection": "ssh", "enabled": True,
    })
    monkeypatch.setattr(device_service, "_runtime_device", lambda device: device)
    monkeypatch.setattr(device_service, "get_driver", lambda _device: driver)
    monkeypatch.setattr(device_service, "encrypt_secret", lambda text: "FERNET:" + text)
    monkeypatch.setattr(device_service, "audit", lambda *args, **kwargs: None)


def test_snapshot_cli_error_does_not_consume_approval_or_apply(monkeypatch):
    driver = FakeDriver("Error: Unrecognized command")
    _base(monkeypatch, driver)
    consumed = []
    monkeypatch.setattr(device_service, "consume_approval_and_create_transaction", lambda _id: consumed.append(_id) or True)
    result = device_service.apply_change("approval-1")
    assert result["status"] == "precheck_failed"
    assert consumed == []


def test_config_apply_cli_error_triggers_preapproved_rollback(monkeypatch):
    driver = FakeDriver("Current configuration", "Error: Unrecognized command found at '^' position.")
    _base(monkeypatch, driver)
    monkeypatch.setattr(device_service, "consume_approval_and_create_transaction", lambda *a, **k: True)
    monkeypatch.setattr(device_service, "update_transaction", lambda *a, **k: True)
    rollback_calls = []
    monkeypatch.setattr(device_service, "_perform_rollback", lambda txid, reason, **kwargs: rollback_calls.append((txid, reason)) or {
        "success": True, "status": "rolled_back",
    })

    result = device_service.apply_change("approval-1")
    assert result["status"] == "apply_failed"
    assert "Unrecognized command" in result["error"]
    assert result["rollback"]["status"] == "rolled_back"
    assert len(rollback_calls) == 1


def test_rollback_cli_error_is_not_marked_as_success(monkeypatch):
    monkeypatch.setattr(device_service, "get_transaction", lambda _id: {
        "id": "tx1", "status": "rolling_back", "device_id": "sw1",
        "rollback_commands": ["undo vlan 300"],
    })
    monkeypatch.setattr(device_service, "get_approval", lambda _id: None)
    monkeypatch.setattr(device_service, "get_device", lambda _id: {
        "id": "sw1", "vendor": "huawei", "connection": "ssh",
    })
    monkeypatch.setattr(device_service, "_runtime_device", lambda device: device)
    monkeypatch.setattr(device_service, "_execute_config", lambda *_args: "Error: Unrecognized command")
    updates = []
    monkeypatch.setattr(device_service, "complete_rollback_transaction", lambda *a, **k: updates.append((a, k)) or True)
    monkeypatch.setattr(device_service, "audit", lambda *args, **kwargs: None)

    result = device_service._perform_rollback("tx1", "test")
    assert result["success"] is False
    assert result["status"] == "rollback_failed"
    assert updates[-1][0][1] == "rollback_failed"


def test_not_contains_verification_allows_valid_delete_state(monkeypatch):
    driver = FakeDriver("Current configuration", "CONFIG-OK", "VLAN 100\nVLAN 300")
    _base(monkeypatch, driver)
    item = _approval()
    item["expected_output_contains"] = ""
    item["expected_output_not_contains"] = ["VLAN 400"]
    item["expected_output_regex"] = [r"VLAN\s+100", r"VLAN\s+300"]
    monkeypatch.setattr(device_service, "get_approval", lambda _id: item)
    transactions = []
    monkeypatch.setattr(device_service, "consume_approval_and_create_transaction", lambda *a, **k: transactions.append((a, k)) or True)
    monkeypatch.setattr(device_service, "finalize_apply_transaction", lambda *a, **k: True)
    monkeypatch.setattr(device_service, "audit", lambda *args, **kwargs: None)

    result = device_service.apply_change("approval-1")
    assert result["status"] == "pending_confirmation"
    assert result["verification"]["passed"] is True
    assert transactions


def test_apply_resolves_command_secrets_only_for_live_execution(monkeypatch):
    driver = FakeDriver("Current configuration", "CONFIG-OK", "VLAN 300")
    _base(monkeypatch, driver)
    item = _approval()
    item["commands"] = ["system-view", "local-user netops password irreversible-cipher ${NETOPS_SECRET_LOGIN}", "commit", "return"]
    item["rollback_commands"] = ["system-view", "undo local-user netops", "commit", "return"]
    monkeypatch.setattr(device_service, "get_approval", lambda _id: item)
    monkeypatch.setenv("NETOPS_SECRET_LOGIN", "S3cret!Value")

    persisted = []
    monkeypatch.setattr(
        device_service,
        "consume_approval_and_create_transaction",
        lambda _txid, approval, *_args, **_kwargs: persisted.append(approval.copy()) or True,
    )
    executed = []
    def execute_config(_device, commands):
        executed.extend(commands)
        return "Device accepted value: S3cret!Value"
    driver.execute_config = execute_config
    monkeypatch.setattr(device_service, "finalize_apply_transaction", lambda *a, **k: True)

    result = device_service.apply_change("approval-1")
    assert result["status"] == "pending_confirmation"
    assert any("S3cret!Value" in command for command in executed)
    assert all("S3cret!Value" not in command for command in persisted[0]["commands"])
    assert all("S3cret!Value" not in command for command in persisted[0]["rollback_commands"])
    assert any("${NETOPS_SECRET_LOGIN}" in command for command in persisted[0]["commands"])
    assert "S3cret!Value" not in result["apply_output"]
    assert "<REDACTED>" in result["apply_output"]


def test_rollback_uses_frozen_secret_even_if_environment_value_rotates(monkeypatch):
    original_secret = "FrozenRollbackSecret-123"
    executed = []
    monkeypatch.setenv("NETOPS_SECRET_LOGIN", "RotatedValue-After-Apply")
    monkeypatch.setattr(device_service, "get_transaction", lambda _id: {
        "id": "tx-frozen", "status": "rolling_back", "device_id": "sw1",
        "approval_id": "approval-secret", 
        "rollback_commands": [f"local-user netops password irreversible-cipher {original_secret}"],
        "secret_values": [original_secret],
    })
    monkeypatch.setattr(device_service, "get_approval", lambda _id: {
        "commands": ["local-user netops password irreversible-cipher ${NETOPS_SECRET_LOGIN}"],
    })
    monkeypatch.setattr(device_service, "get_device", lambda _id: {
        "id": "sw1", "vendor": "huawei", "connection": "ssh",
    })
    monkeypatch.setattr(device_service, "_runtime_device", lambda value: value)
    def run_config(_device, commands):
        executed.extend(commands)
        return f"Device echoed: {original_secret}"
    monkeypatch.setattr(device_service, "_execute_config", run_config)
    monkeypatch.setattr(device_service, "complete_rollback_transaction", lambda *_args: True)
    monkeypatch.setattr(device_service, "audit", lambda *_args, **_kwargs: None)

    result = device_service._perform_rollback("tx-frozen", "test")
    assert result["success"] is True
    assert original_secret in executed[0]
    assert original_secret not in result["output"]
    assert "<REDACTED>" in result["output"]

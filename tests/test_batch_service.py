from app.services import batch_service


def test_batch_stops_on_failure_and_rolls_back_previous_devices(monkeypatch):
    approvals = {
        "a1": {"id": "a1", "device_id": "sw1", "status": "approved"},
        "a2": {"id": "a2", "device_id": "sw2", "status": "approved"},
    }
    monkeypatch.setattr(batch_service, "get_approval", lambda aid: approvals.get(aid))
    monkeypatch.setattr(batch_service, "_preflight_approval", lambda *args: {"success": True})
    monkeypatch.setattr(batch_service, "audit", lambda *args, **kwargs: None)
    calls = []
    def apply(aid):
        calls.append(aid)
        if aid == "a1":
            return {"success": True, "status": "pending_confirmation", "transaction_id": "tx1"}
        return {"success": False, "status": "apply_failed", "error": "simulated failure"}
    monkeypatch.setattr(batch_service, "apply_change", apply)
    monkeypatch.setattr(batch_service, "get_transaction", lambda txid: {"status": "pending_confirmation"})
    rollbacks = []
    monkeypatch.setattr(batch_service, "rollback_change", lambda txid: rollbacks.append(txid) or {"success": True, "status": "rolled_back"})

    result = batch_service.apply_approved_batch(["a1", "a2"], True)
    assert calls == ["a1", "a2"]
    assert rollbacks == ["tx1"]
    assert result["success"] is False
    assert result["status"] == "failed_compensated"


def test_batch_preflight_rejects_duplicate_devices_before_execution(monkeypatch):
    monkeypatch.setattr(batch_service, "get_approval", lambda aid: {
        "id": aid, "device_id": "sw1", "status": "approved",
    })
    monkeypatch.setattr(batch_service, "_preflight_approval", lambda *args: {"success": True})
    monkeypatch.setattr(batch_service, "apply_change", lambda _aid: (_ for _ in ()).throw(AssertionError("must not execute")))
    import pytest
    with pytest.raises(ValueError, match="同一批次"):
        batch_service.apply_approved_batch(["a1", "a2"])


def test_batch_preflights_every_approval_before_first_device(monkeypatch):
    approvals = {
        "a1": {"id": "a1", "device_id": "sw1", "status": "approved"},
        "a2": {"id": "a2", "device_id": "sw2", "status": "approved"},
    }
    monkeypatch.setattr(batch_service, "get_approval", lambda aid: approvals.get(aid))
    visited = []
    def preflight(aid, item, principal):
        visited.append(aid)
        if aid == "a2":
            raise ValueError("第二台设备不是 SSH")
        return {"success": True}
    monkeypatch.setattr(batch_service, "_preflight_approval", preflight)
    monkeypatch.setattr(batch_service, "apply_change", lambda _aid: (_ for _ in ()).throw(AssertionError("must not apply")))
    import pytest
    with pytest.raises(ValueError, match="不是 SSH"):
        batch_service.apply_approved_batch(["a1", "a2"])
    assert visited == ["a1", "a2"]


def test_batch_reports_incomplete_compensation(monkeypatch):
    approvals = {
        "a1": {"id": "a1", "device_id": "sw1", "status": "approved"},
        "a2": {"id": "a2", "device_id": "sw2", "status": "approved"},
    }
    monkeypatch.setattr(batch_service, "get_approval", lambda aid: approvals.get(aid))
    monkeypatch.setattr(batch_service, "_preflight_approval", lambda *args: {"success": True})
    monkeypatch.setattr(batch_service, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_service, "apply_change", lambda aid: (
        {"success": True, "status": "pending_confirmation", "transaction_id": "tx1"}
        if aid == "a1" else {"success": False, "status": "apply_failed"}
    ))
    monkeypatch.setattr(batch_service, "get_transaction", lambda _txid: {"status": "pending_confirmation"})
    monkeypatch.setattr(batch_service, "rollback_change", lambda _txid: {"success": False, "status": "rollback_failed"})
    result = batch_service.apply_approved_batch(["a1", "a2"], True)
    assert result["status"] == "failed_compensation_incomplete"


def test_batch_preflight_checks_password_env_before_any_network_change(monkeypatch):
    item = {
        "id": "a1", "device_id": "sw1", "status": "approved",
        "commands": ["vlan 300"], "rollback_commands": ["undo vlan 300"],
        "verify_command": "display vlan 300", "expected_output_contains": "VLAN 300",
        "expected_output_contains_all": [], "expected_output_not_contains": [], "expected_output_regex": [],
        "requested_by": "alice", "approved_by": "bob",
    }
    device = {
        "id": "sw1", "vendor": "huawei", "platform": "huawei_vrp",
        "connection": "ssh", "enabled": True, "host": "192.0.2.10", "port": 22,
        "username": "netops", "password_env": "MISSING_DEVICE_PASSWORD",
    }
    monkeypatch.setattr(batch_service, "get_device", lambda _id: device)
    monkeypatch.setattr(batch_service, "_approval_assertions", lambda _item: {})
    monkeypatch.setattr(batch_service, "resolve_command_secrets", lambda values: values)
    monkeypatch.setattr(batch_service, "_validate_config_lists", lambda commands, rollback: (commands, rollback))
    monkeypatch.setattr(batch_service, "_runtime_device", lambda value: value)
    monkeypatch.setattr(batch_service, "resolve_password", lambda _device: (_ for _ in ()).throw(
        RuntimeError("missing device credential")))
    import pytest
    with pytest.raises(RuntimeError, match="missing device credential"):
        batch_service._preflight_approval("a1", item, {"id": "alice", "role": "operator"})


def test_batch_failure_on_first_device_is_not_called_partial_when_compensation_disabled(monkeypatch):
    monkeypatch.setattr(batch_service, "get_approval", lambda aid: {
        "id": aid, "device_id": "sw1", "status": "approved",
    })
    monkeypatch.setattr(batch_service, "_preflight_approval", lambda *args: {"success": True})
    monkeypatch.setattr(batch_service, "audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch_service, "apply_change", lambda _aid: {
        "success": False, "status": "apply_failed", "error": "expected test failure",
    })
    result = batch_service.apply_approved_batch(["a1"], rollback_previous_on_failure=False)
    assert result["status"] == "failed_no_prior_changes"


def test_batch_confirm_returns_each_result_even_when_one_confirm_raises(monkeypatch):
    monkeypatch.setattr(batch_service, "current_principal", lambda: {"id": "approver01", "role": "approver"})
    def confirm(txid, confirmed_by=None):
        if txid == "tx2":
            raise RuntimeError("password cipher ConfirmSecret123")
        return {"success": True, "transaction_id": txid, "status": "confirmed"}
    monkeypatch.setattr(batch_service, "confirm_change", confirm)
    result = batch_service.confirm_approved_batch(["tx1", "tx2", "tx3"])
    assert result["success"] is False
    assert result["confirmed_count"] == 2
    assert result["results"][1]["status"] == "confirm_exception"
    assert "ConfirmSecret123" not in result["results"][1]["error"]

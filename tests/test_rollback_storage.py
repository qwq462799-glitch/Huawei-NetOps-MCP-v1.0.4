from app import storage

def test_transaction_persistence_and_confirmation(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/rollback.db")
    storage.init_db()
    storage.create_approval(
        "approval-1", "sw1", ["vlan 100"], ["undo vlan 100"],
        "display vlan", "VLAN", 300
    )
    approval = {
        "id": "approval-1", "device_id": "sw1",
        "rollback_commands": ["undo vlan 100"],
        "verify_command": "display vlan",
        "expected_output_contains": "VLAN",
    }
    storage.create_transaction(
        "tx-1", approval, "encrypted-snapshot", "applied", "VLAN 100",
        "2999-01-01T00:00:00+00:00"
    )
    tx = storage.get_transaction("tx-1")
    assert tx["status"] == "pending_confirmation"
    assert tx["rollback_commands"] == ["undo vlan 100"]
    assert storage.confirm_transaction("tx-1") is True
    assert storage.get_transaction("tx-1")["status"] == "confirmed"
    assert storage.claim_due_rollbacks("3000-01-01T00:00:00+00:00") == []

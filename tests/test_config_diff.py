from app.services import config_diff


def test_diff_transaction_returns_redacted_unified_diff(monkeypatch):
    monkeypatch.setattr(config_diff, "get_transaction", lambda _id: {
        "id": "tx1", "device_id": "sw1", "status": "confirmed", "snapshot_encrypted": "enc",
    })
    monkeypatch.setattr(config_diff, "get_device", lambda _id: {"vendor": "huawei"})
    monkeypatch.setattr(config_diff, "decrypt_secret", lambda _v: "sysname OLD\nlocal-user x password irreversible-cipher TOPSECRET")
    monkeypatch.setattr(config_diff, "execute", lambda *_a: {
        "success": True, "output": "sysname NEW\nlocal-user x password irreversible-cipher TOPSECRET2",
    })
    result = config_diff.diff_transaction("tx1")
    assert result["success"] is True
    assert "sysname OLD" in result["diff"]
    assert "sysname NEW" in result["diff"]
    assert "TOPSECRET" not in result["diff"]
    assert "TOPSECRET2" not in result["diff"]

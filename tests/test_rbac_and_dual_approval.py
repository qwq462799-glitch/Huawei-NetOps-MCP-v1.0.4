from app import storage
from app.config import settings
from app.security.rbac import current_principal, require_permission
import pytest


def test_current_principal_comes_from_process_settings(monkeypatch):
    monkeypatch.setattr(settings, "operator_id", "alice")
    monkeypatch.setattr(settings, "operator_role", "operator")
    assert current_principal() == {"id": "alice", "role": "operator"}
    require_permission("change_request")
    with pytest.raises(PermissionError):
        require_permission("change_approve")


def test_dual_approval_requires_a_different_actor(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'rbac.db'}")
    storage.init_db()
    storage.create_approval(
        "a1", "sw1", ["vlan 10"], ["undo vlan 10"], "display vlan", "VLAN", 300,
        requested_by="alice",
    )
    assert storage.approve("a1", approved_by="alice", require_distinct=True) is False
    assert storage.get_approval("a1")["status"] == "pending"
    assert storage.approve("a1", approved_by="bob", require_distinct=True) is True
    row = storage.get_approval("a1")
    assert row["requested_by"] == "alice"
    assert row["approved_by"] == "bob"
    assert row["status"] == "approved"


def test_settings_reads_netops_prefixed_environment(monkeypatch):
    from app.config import Settings
    monkeypatch.setenv("NETOPS_OPERATOR_ID", "netsec02")
    monkeypatch.setenv("NETOPS_OPERATOR_ROLE", "approver")
    monkeypatch.setenv("NETOPS_REQUIRE_DUAL_APPROVAL", "true")
    loaded = Settings(_env_file=None)
    assert loaded.operator_id == "netsec02"
    assert loaded.operator_role == "approver"
    assert loaded.require_dual_approval is True


def test_unconfigured_settings_default_to_viewer_and_require_dual_approval(monkeypatch):
    from app.config import Settings
    for name in ("NETOPS_OPERATOR_ID", "NETOPS_OPERATOR_ROLE", "NETOPS_REQUIRE_DUAL_APPROVAL"):
        monkeypatch.delenv(name, raising=False)
    defaults = Settings(_env_file=None)
    assert defaults.operator_id == "local-viewer"
    assert defaults.operator_role == "viewer"
    assert defaults.require_dual_approval is True


def test_current_principal_rejects_identity_injection_characters(monkeypatch):
    monkeypatch.setattr(settings, "operator_id", "operator\nadmin")
    monkeypatch.setattr(settings, "operator_role", "operator")
    with pytest.raises(PermissionError):
        current_principal()

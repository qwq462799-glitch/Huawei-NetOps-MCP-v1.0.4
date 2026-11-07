import json

from app import storage
from app.config import settings
from app.security import command_secrets
from app.security.command_secrets import resolve_command_secrets, redact_command_secrets
from app.security.redaction import redact_text, redact_value
import pytest


def test_approval_command_plans_are_encrypted_at_rest(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'encrypted.db'}")
    storage.init_db()
    storage.create_approval(
        "a-sec", "sw1", ["local-user netops password irreversible-cipher MySecret123"],
        ["undo local-user netops"], "display users", "netops", 300, requested_by="alice",
    )
    with storage.connect() as con:
        raw = con.execute("SELECT commands,rollback_commands FROM approvals WHERE id='a-sec'").fetchone()
    assert raw["commands"].startswith("fernet:v1:")
    assert "MySecret123" not in raw["commands"]
    assert storage.get_approval("a-sec")["commands"] == [
        "local-user netops password irreversible-cipher MySecret123"
    ]


def test_audit_redacts_password_lines_and_secret_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'audit-redact.db'}")
    storage.init_db()
    storage.audit("alice", "config.apply", "sw1", {
        "command": "local-user netops password irreversible-cipher MySecret123",
        "password": "direct-secret",
    })
    row = storage.recent_audit()[0]
    assert "MySecret123" not in json.dumps(row)
    assert "direct-secret" not in json.dumps(row)
    assert "<REDACTED>" in row["details"]["command"]


def test_redaction_handles_cisco_secret_index_and_private_key_block():
    text = "username admin secret 5 $1$VerySecretHash\n-----BEGIN PRIVATE KEY-----\nABCDEFSECRET\n-----END PRIVATE KEY-----"
    redacted = redact_text(text)
    assert "VerySecretHash" not in redacted
    assert "ABCDEFSECRET" not in redacted
    assert "PRIVATE KEY MATERIAL REDACTED" in redacted


def test_recursive_redaction_masks_sensitive_dictionary_keys():
    clean = redact_value({"token": "abc", "nested": {"community": "public", "state": "ok"}})
    assert clean == {"token": "<REDACTED>", "nested": {"community": "<REDACTED>", "state": "ok"}}


def test_command_secret_placeholders_resolve_and_reject_multiline(monkeypatch):
    monkeypatch.setenv("NETOPS_SECRET_BGP", "S3cret!Hash")
    assert resolve_command_secrets(["peer 192.0.2.1 password ${NETOPS_SECRET_BGP}"]) == [
        "peer 192.0.2.1 password S3cret!Hash"
    ]
    monkeypatch.setenv("NETOPS_SECRET_BAD", "bad\ncommand")
    with pytest.raises(ValueError, match="换行/分隔符"):
        resolve_command_secrets(["peer password ${NETOPS_SECRET_BAD}"])


def test_redaction_masks_tacacs_radius_and_ike_keys():
    text = (
        "tacacs-server host 192.0.2.10 key 7 TacacsSecret\n"
        "radius-server key 0 RadiusSecret\n"
        "crypto isakmp key IKESecret address 192.0.2.20"
    )
    clean = redact_text(text)
    for secret in ("TacacsSecret", "RadiusSecret", "IKESecret"):
        assert secret not in clean


def test_process_environment_secret_overrides_project_dotenv(tmp_path, monkeypatch):
    monkeypatch.setattr(command_secrets, "_PROJECT_ENV_FILE", tmp_path / ".env")
    (tmp_path / ".env").write_text("NETOPS_SECRET_PROFILE=project-value\n", encoding="utf-8")
    monkeypatch.setenv("NETOPS_SECRET_PROFILE", "profile-value")
    assert resolve_command_secrets(["peer password ${NETOPS_SECRET_PROFILE}"]) == [
        "peer password profile-value"
    ]


def test_command_secret_redaction_masks_literal_values_from_device_echo(monkeypatch):
    monkeypatch.setenv("NETOPS_SECRET_ECHO", "UniqueDeviceSecret-2026")
    commands = ["peer password ${NETOPS_SECRET_ECHO}"]
    output = "Device accepted value: UniqueDeviceSecret-2026"
    safe = redact_command_secrets(output, commands)
    assert "UniqueDeviceSecret-2026" not in safe
    assert "<REDACTED>" in safe

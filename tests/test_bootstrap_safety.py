from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("netops_bootstrap", ROOT / "scripts" / "bootstrap.py")
assert SPEC and SPEC.loader
BOOTSTRAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOTSTRAP)


def test_bootstrap_generates_key_on_fresh_install(tmp_path: Path):
    (tmp_path / ".env.example").write_text(
        "DATABASE_URL=sqlite:///./data/netops.db\nCREDENTIAL_ENCRYPTION_KEY=\n",
        encoding="utf-8",
    )
    BOOTSTRAP._ensure_env(tmp_path)
    text = (tmp_path / ".env").read_text(encoding="utf-8")
    key = next(line.split("=", 1)[1] for line in text.splitlines()
               if line.startswith("CREDENTIAL_ENCRYPTION_KEY="))
    Fernet(key.encode("ascii"))
    original = key
    BOOTSTRAP._ensure_env(tmp_path)
    text_again = (tmp_path / ".env").read_text(encoding="utf-8")
    key_again = next(line.split("=", 1)[1] for line in text_again.splitlines()
                     if line.startswith("CREDENTIAL_ENCRYPTION_KEY="))
    assert key_again == original


def test_bootstrap_refuses_new_key_when_database_exists_and_key_missing(tmp_path: Path):
    (tmp_path / ".env.example").write_text(
        "DATABASE_URL=sqlite:///./data/netops.db\nCREDENTIAL_ENCRYPTION_KEY=\n",
        encoding="utf-8",
    )
    database = tmp_path / "data" / "netops.db"
    database.parent.mkdir()
    database.write_bytes(b"existing database placeholder")
    with pytest.raises(RuntimeError, match="已有 SQLite 数据库"):
        BOOTSTRAP._ensure_env(tmp_path)
    assert "CREDENTIAL_ENCRYPTION_KEY=" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_bootstrap_rejects_duplicate_encryption_key_definitions(tmp_path: Path):
    (tmp_path / ".env").write_text(
        "DATABASE_URL=sqlite:///./data/netops.db\n"
        "CREDENTIAL_ENCRYPTION_KEY=\nCREDENTIAL_ENCRYPTION_KEY=\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="重复定义"):
        BOOTSTRAP._ensure_env(tmp_path)


def test_bootstrap_persists_process_environment_key_for_future_harness_restarts(tmp_path: Path, monkeypatch):
    key = Fernet.generate_key().decode("ascii")
    (tmp_path / ".env.example").write_text(
        "DATABASE_URL=sqlite:///./data/netops.db\nCREDENTIAL_ENCRYPTION_KEY=\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", key)
    BOOTSTRAP._ensure_env(tmp_path)
    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f"CREDENTIAL_ENCRYPTION_KEY={key}" in content


def test_bootstrap_rejects_conflicting_process_and_file_keys(tmp_path: Path, monkeypatch):
    file_key = Fernet.generate_key().decode("ascii")
    process_key = Fernet.generate_key().decode("ascii")
    (tmp_path / ".env").write_text(
        f"DATABASE_URL=sqlite:///./data/netops.db\nCREDENTIAL_ENCRYPTION_KEY={file_key}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", process_key)
    with pytest.raises(RuntimeError, match="不一致"):
        BOOTSTRAP._ensure_env(tmp_path)


def test_bootstrap_checks_database_url_process_override(tmp_path: Path, monkeypatch):
    (tmp_path / ".env.example").write_text(
        "DATABASE_URL=sqlite:///./data/default.db\nCREDENTIAL_ENCRYPTION_KEY=\n",
        encoding="utf-8",
    )
    external_db = tmp_path / "external" / "existing.db"
    external_db.parent.mkdir()
    external_db.write_bytes(b"existing database placeholder")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{external_db}")
    with pytest.raises(RuntimeError, match="已有 SQLite 数据库"):
        BOOTSTRAP._ensure_env(tmp_path)

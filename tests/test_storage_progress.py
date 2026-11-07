import sqlite3
from pathlib import Path

from app import storage
from app.config import settings


def use_db(monkeypatch, tmp_path, name="jobs.db"):
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / name}")
    storage.init_db()


def _create_approved(monkeypatch, tmp_path):
    use_db(monkeypatch, tmp_path)
    storage.create_approval(
        "approval-job", "sw1", ["vlan 300"], ["undo vlan 300"],
        "display vlan", "VLAN", 300,
        expected_output_not_contains=["VLAN 400"],
        expected_output_regex=[r"VLAN\s+\d+"],
    )
    assert storage.approve("approval-job") is True
    return storage.get_approval("approval-job")


def test_new_verification_columns_persist_and_read_back(monkeypatch, tmp_path):
    approval = _create_approved(monkeypatch, tmp_path)
    assert approval["expected_output_not_contains"] == ["VLAN 400"]
    assert approval["expected_output_regex"] == [r"VLAN\s+\d+"]
    storage.create_transaction(
        "tx-job", approval, "encrypted-snapshot", "apply", "VLAN 300",
        "2999-01-01T00:00:00+00:00",
    )
    tx = storage.get_transaction("tx-job")
    assert tx["expected_output_not_contains"] == ["VLAN 400"]
    assert tx["expected_output_regex"] == [r"VLAN\s+\d+"]


def test_manual_rollback_is_atomically_claimed_once(monkeypatch, tmp_path):
    approval = _create_approved(monkeypatch, tmp_path)
    storage.create_transaction(
        "tx-race", approval, "encrypted", "apply", "VLAN 300",
        "2999-01-01T00:00:00+00:00",
    )
    assert storage.claim_manual_rollback("tx-race") is True
    assert storage.claim_manual_rollback("tx-race") is False
    assert storage.confirm_transaction("tx-race") is False
    assert storage.get_transaction("tx-race")["status"] == "rolling_back"


def test_old_database_is_upgraded_without_deleting_existing_approval(monkeypatch, tmp_path):
    db = tmp_path / "old.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{db}")
    with sqlite3.connect(db) as con:
        con.executescript("""
        CREATE TABLE devices(id TEXT PRIMARY KEY,payload TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE approvals(
          id TEXT PRIMARY KEY, device_id TEXT NOT NULL, commands TEXT NOT NULL,
          status TEXT NOT NULL, created_at TEXT NOT NULL, approved_at TEXT,
          rollback_commands TEXT NOT NULL DEFAULT '[]', verify_command TEXT NOT NULL DEFAULT '',
          expected_output_contains TEXT NOT NULL DEFAULT '', rollback_after_seconds INTEGER NOT NULL DEFAULT 300
        );
        CREATE TABLE change_transactions(
          id TEXT PRIMARY KEY,approval_id TEXT NOT NULL UNIQUE,device_id TEXT NOT NULL,
          snapshot_encrypted TEXT,status TEXT NOT NULL,rollback_due_at TEXT,
          rollback_commands TEXT NOT NULL,verify_command TEXT NOT NULL,
          expected_output_contains TEXT NOT NULL,apply_output TEXT,verify_output TEXT,
          rollback_output TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
        );
        CREATE TABLE audit(id INTEGER PRIMARY KEY AUTOINCREMENT,actor TEXT NOT NULL,action TEXT NOT NULL,
          device_id TEXT,details TEXT NOT NULL,created_at TEXT NOT NULL);
        INSERT INTO approvals(id,device_id,commands,status,created_at)
          VALUES('old-a','sw1','["vlan 100"]','pending','2026-11-01');
        """)
    storage.init_db()
    item = storage.get_approval("old-a")
    assert item is not None
    assert item["commands"] == ["vlan 100"]
    assert item["expected_output_not_contains"] == []
    with storage.connect() as con:
        columns = {r["name"] for r in con.execute("PRAGMA table_info(change_transactions)")}
    assert "expected_output_regex" in columns
    assert "secret_values_encrypted" in columns


def test_change_job_progress_and_interrupted_recovery(monkeypatch, tmp_path):
    _create_approved(monkeypatch, tmp_path)
    storage.create_change_job("job1", "approval-job")
    storage.append_change_job_progress("approval-job", 25, "下发中")
    job = storage.get_change_job("approval-job")
    assert job["status"] == "running"
    assert job["events"][-1]["message"] == "下发中"

    storage.create_approval("approval-stuck", "sw1", ["vlan 1"], ["undo vlan 1"],
                             "display vlan", "VLAN", 300)
    storage.approve("approval-stuck")
    storage.create_change_job("job2", "approval-stuck")
    storage.append_change_job_progress("approval-stuck", 50, "验证中")
    assert storage.recover_interrupted_change_jobs() == 2
    assert storage.get_change_job("approval-job")["status"] == "interrupted"
    assert storage.get_change_job("approval-stuck")["status"] == "interrupted"


def test_interrupted_apply_is_claimed_for_recovery_and_stale_rollback_is_not_replayed(monkeypatch, tmp_path):
    approval = _create_approved(monkeypatch, tmp_path)
    storage.create_transaction(
        "tx-applying", approval, "encrypted", "", "", None, initial_status="applying",
    )
    assert storage.claim_interrupted_applications() == ["tx-applying"]
    assert storage.get_transaction("tx-applying")["status"] == "rolling_back"
    # Simulate a rollback that has remained in progress beyond the recovery safety window.
    with storage.connect() as con:
        con.execute("UPDATE change_transactions SET updated_at=? WHERE id=?", ("2000-01-01T00:00:00+00:00", "tx-applying"))
    assert storage.mark_stale_rollbacks_failed(age_seconds=60) == 1
    tx = storage.get_transaction("tx-applying")
    assert tx["status"] == "rollback_failed"
    assert "人工核查" in tx["rollback_output"]


def test_finalize_apply_transitions_only_applying_transaction(monkeypatch, tmp_path):
    approval = _create_approved(monkeypatch, tmp_path)
    storage.create_transaction(
        "tx-finalize", approval, "encrypted", "", "", None, initial_status="applying",
    )
    assert storage.finalize_apply_transaction(
        "tx-finalize", "apply output", "verify output", "2999-01-01T00:00:00+00:00"
    ) is True
    assert storage.finalize_apply_transaction(
        "tx-finalize", "another", "another", "2999-01-01T00:00:00+00:00"
    ) is False
    tx = storage.get_transaction("tx-finalize")
    assert tx["status"] == "pending_confirmation"
    assert tx["apply_output"] == "apply output"


def test_approval_consumption_and_applying_transaction_are_atomic(monkeypatch, tmp_path):
    approval = _create_approved(monkeypatch, tmp_path)
    assert storage.consume_approval_and_create_transaction(
        "tx-atomic", approval, "encrypted-snapshot", initial_status="applying"
    ) is True
    assert storage.get_approval("approval-job")["status"] == "consumed"
    tx = storage.get_transaction("tx-atomic")
    assert tx["status"] == "applying"
    assert tx["snapshot_encrypted"] == "encrypted-snapshot"
    # 同一审批不能被第二次消费，也不能产生第二笔事务。
    assert storage.consume_approval_and_create_transaction(
        "tx-atomic-2", approval, "encrypted-snapshot", initial_status="applying"
    ) is False
    assert storage.get_transaction("tx-atomic-2") is None


def test_atomic_transaction_insert_failure_keeps_approval_approved(monkeypatch, tmp_path):
    first = _create_approved(monkeypatch, tmp_path)
    assert storage.consume_approval_and_create_transaction(
        "tx-shared", first, "encrypted-first", initial_status="applying"
    ) is True

    storage.create_approval(
        "approval-second", "sw1", ["vlan 400"], ["undo vlan 400"],
        "display vlan", "VLAN", 300,
    )
    assert storage.approve("approval-second") is True
    second = storage.get_approval("approval-second")

    # 模拟事务主键冲突：审批状态更新必须随 INSERT 失败一起回滚。
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        storage.consume_approval_and_create_transaction(
            "tx-shared", second, "encrypted-second", initial_status="applying"
        )

    assert storage.get_approval("approval-second")["status"] == "approved"
    assert storage.get_transaction("tx-shared")["approval_id"] == "approval-job"


def test_interrupted_apply_claim_has_staleness_guard(monkeypatch, tmp_path):
    approval = _create_approved(monkeypatch, tmp_path)
    storage.create_transaction("tx-active", approval, "encrypted", "", "", None, initial_status="applying")
    assert storage.claim_interrupted_applications(age_seconds=600) == []
    assert storage.get_transaction("tx-active")["status"] == "applying"
    assert storage.claim_interrupted_applications(age_seconds=0) == ["tx-active"]


def test_stale_rollback_is_marked_uncertain_not_replayed(monkeypatch, tmp_path):
    approval = _create_approved(monkeypatch, tmp_path)
    storage.create_transaction("tx-rollback-stale", approval, "encrypted", "", "", None, initial_status="applying")
    assert storage.claim_interrupted_applications(age_seconds=0) == ["tx-rollback-stale"]
    # Backdate the rolling_back timestamp to simulate a crashed rollback owner.
    with storage.connect() as con:
        con.execute("UPDATE change_transactions SET updated_at='2000-01-01T00:00:00+00:00' WHERE id=?", ("tx-rollback-stale",))
    assert storage.mark_stale_rollbacks_failed(age_seconds=600) == 1
    assert storage.get_transaction("tx-rollback-stale")["status"] == "rollback_failed"


def test_change_job_recovery_ignores_recent_active_job(monkeypatch, tmp_path):
    _create_approved(monkeypatch, tmp_path)
    storage.create_change_job("job-active", "approval-job")
    storage.append_change_job_progress("approval-job", 40, "执行中")
    assert storage.recover_interrupted_change_jobs(age_seconds=600) == 0
    assert storage.get_change_job("approval-job")["status"] == "running"


def test_transaction_freezes_resolved_rollback_commands_and_secrets_encrypted(monkeypatch, tmp_path):
    approval = _create_approved(monkeypatch, tmp_path)
    resolved_rollback = ["local-user netops password irreversible-cipher FrozenRollbackSecret"]
    storage.create_transaction(
        "tx-frozen-secret", approval, "encrypted-snapshot", "", "", None,
        initial_status="applying",
        rollback_commands_override=resolved_rollback,
        secret_values=["FrozenRollbackSecret"],
    )
    with storage.connect() as con:
        row = con.execute(
            "SELECT rollback_commands,secret_values_encrypted FROM change_transactions WHERE id=?",
            ("tx-frozen-secret",),
        ).fetchone()
    assert "FrozenRollbackSecret" not in row["rollback_commands"]
    assert "FrozenRollbackSecret" not in row["secret_values_encrypted"]
    tx = storage.get_transaction("tx-frozen-secret")
    assert tx["rollback_commands"] == resolved_rollback
    assert tx["secret_values"] == ["FrozenRollbackSecret"]

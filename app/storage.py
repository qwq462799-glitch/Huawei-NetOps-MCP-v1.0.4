"""SQLite persistence layer with additive, non-destructive schema migrations."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from filelock import FileLock
from app.config import settings
from app.security.redaction import redact_text, redact_value


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db_path() -> Path:
    url = settings.database_url
    if not url.startswith("sqlite:///"):
        raise RuntimeError("当前版本存储层使用 SQLite；PostgreSQL 适配器需要独立实现。")
    path = Path(url.replace("sqlite:///", "", 1)).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def worker_lock_path() -> str:
    """Stable lock-file path shared by Harness MCP instances using this SQLite DB."""
    return str(_db_path()) + ".rollback-worker.lock"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path(), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_columns(con: sqlite3.Connection, table: str, migrations: dict[str, str]) -> None:
    columns = _columns(con, table)
    for name, definition in migrations.items():
        if name not in columns:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_db() -> None:
    """Serialize additive schema upgrades across Harness stdio child processes."""
    lock = FileLock(str(_db_path()) + ".schema.lock", timeout=60)
    with lock:
        _init_db_locked()


def _init_db_locked() -> None:
    """Create current schema and safely upgrade databases from earlier deployed releases."""
    with connect() as con:
        # Set WAL once while the cross-process schema lock is held, not on every tool call.
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript("""
        CREATE TABLE IF NOT EXISTS devices (
          id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approvals (
          id TEXT PRIMARY KEY, device_id TEXT NOT NULL, commands TEXT NOT NULL,
          status TEXT NOT NULL, created_at TEXT NOT NULL, approved_at TEXT,
          rollback_commands TEXT NOT NULL DEFAULT '[]',
          verify_command TEXT NOT NULL DEFAULT '',
          expected_output_contains TEXT NOT NULL DEFAULT '',
          rollback_after_seconds INTEGER NOT NULL DEFAULT 300,
          expected_output_contains_all TEXT NOT NULL DEFAULT '[]',
          expected_output_not_contains TEXT NOT NULL DEFAULT '[]',
          expected_output_regex TEXT NOT NULL DEFAULT '[]',
          requested_by TEXT, approved_by TEXT
        );
        CREATE TABLE IF NOT EXISTS change_transactions (
          id TEXT PRIMARY KEY,
          approval_id TEXT NOT NULL UNIQUE,
          device_id TEXT NOT NULL,
          snapshot_encrypted TEXT,
          status TEXT NOT NULL,
          rollback_due_at TEXT,
          rollback_commands TEXT NOT NULL,
          verify_command TEXT NOT NULL,
          expected_output_contains TEXT NOT NULL,
          apply_output TEXT,
          verify_output TEXT,
          rollback_output TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          expected_output_contains_all TEXT NOT NULL DEFAULT '[]',
          expected_output_not_contains TEXT NOT NULL DEFAULT '[]',
          expected_output_regex TEXT NOT NULL DEFAULT '[]',
          secret_values_encrypted TEXT,
          confirmed_by TEXT, rollback_by TEXT,
          FOREIGN KEY(approval_id) REFERENCES approvals(id)
        );
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT, actor TEXT NOT NULL,
          action TEXT NOT NULL, device_id TEXT, details TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS change_jobs (
          id TEXT PRIMARY KEY,
          approval_id TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL,
          progress INTEGER NOT NULL DEFAULT 0,
          message TEXT NOT NULL DEFAULT '',
          events TEXT NOT NULL DEFAULT '[]',
          result TEXT,
          error TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(approval_id) REFERENCES approvals(id)
        );
        CREATE INDEX IF NOT EXISTS idx_transactions_due
          ON change_transactions(status, rollback_due_at);
        CREATE INDEX IF NOT EXISTS idx_audit_created ON audit(created_at);
        """)
        _add_columns(con, "approvals", {
            "requested_by": "TEXT",
            "approved_by": "TEXT",
            "rollback_commands": "TEXT NOT NULL DEFAULT '[]'",
            "verify_command": "TEXT NOT NULL DEFAULT ''",
            "expected_output_contains": "TEXT NOT NULL DEFAULT ''",
            "rollback_after_seconds": "INTEGER NOT NULL DEFAULT 300",
            "expected_output_contains_all": "TEXT NOT NULL DEFAULT '[]'",
            "expected_output_not_contains": "TEXT NOT NULL DEFAULT '[]'",
            "expected_output_regex": "TEXT NOT NULL DEFAULT '[]'",
        })
        _add_columns(con, "change_transactions", {
            "confirmed_by": "TEXT",
            "rollback_by": "TEXT",
            "expected_output_contains_all": "TEXT NOT NULL DEFAULT '[]'",
            "expected_output_not_contains": "TEXT NOT NULL DEFAULT '[]'",
            "expected_output_regex": "TEXT NOT NULL DEFAULT '[]'",
            "secret_values_encrypted": "TEXT",
        })
        # Upgrade legacy plaintext command plans only when the existing Fernet key is available.
        # Never generate or rotate a key during database migration.
        if settings.credential_encryption_key:
            for row in con.execute("SELECT id,commands,rollback_commands FROM approvals").fetchall():
                if row["commands"] and not str(row["commands"]).startswith("fernet:v1:"):
                    con.execute("UPDATE approvals SET commands=? WHERE id=?", (_pack_sensitive_list(json.loads(row["commands"])), row["id"]))
                if row["rollback_commands"] and not str(row["rollback_commands"]).startswith("fernet:v1:"):
                    con.execute("UPDATE approvals SET rollback_commands=? WHERE id=?", (_pack_sensitive_list(json.loads(row["rollback_commands"])), row["id"]))
            for row in con.execute("SELECT id,rollback_commands FROM change_transactions").fetchall():
                if row["rollback_commands"] and not str(row["rollback_commands"]).startswith("fernet:v1:"):
                    con.execute("UPDATE change_transactions SET rollback_commands=? WHERE id=?", (_pack_sensitive_list(json.loads(row["rollback_commands"])), row["id"]))


def _pack_sensitive_list(values: list[str]) -> str:
    """Encrypt command arrays at rest; retain a marker for legacy migration reads."""
    from app.security.credentials import encrypt_secret
    payload = json.dumps(values, ensure_ascii=False)
    return "fernet:v1:" + encrypt_secret(payload)


def _unpack_sensitive_list(value: str | None) -> list[str]:
    if not value:
        return []
    if value.startswith("fernet:v1:"):
        from app.security.credentials import decrypt_secret
        return json.loads(decrypt_secret(value[len("fernet:v1:"):]))
    # Backward compatibility for approvals/transactions created by earlier releases.
    return json.loads(value)


def save_device(payload: dict) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO devices(id,payload,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
            (payload["id"], json.dumps(payload), utcnow()),
        )


def get_device(device_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT payload FROM devices WHERE id=?", (device_id,)).fetchone()
        return json.loads(row["payload"]) if row else None


def list_devices() -> list[dict]:
    with connect() as con:
        rows = con.execute("SELECT payload FROM devices ORDER BY id").fetchall()
        return [json.loads(row["payload"]) for row in rows]


def audit(actor: str, action: str, device_id: str | None, details: dict) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO audit(actor,action,device_id,details,created_at) VALUES(?,?,?,?,?)",
            (actor, action, device_id, json.dumps(redact_value(details), ensure_ascii=False), utcnow()),
        )


def create_approval(
    approval_id: str,
    device_id: str,
    commands: list[str],
    rollback_commands: list[str],
    verify_command: str,
    expected_output_contains: str,
    rollback_after_seconds: int,
    expected_output_contains_all: list[str] | None = None,
    expected_output_not_contains: list[str] | None = None,
    expected_output_regex: list[str] | None = None,
    requested_by: str | None = None,
) -> None:
    with connect() as con:
        con.execute(
            """INSERT INTO approvals(
              id,device_id,commands,status,created_at,rollback_commands,
              verify_command,expected_output_contains,rollback_after_seconds,
              expected_output_contains_all,expected_output_not_contains,expected_output_regex,requested_by
            ) VALUES(?,?,?,'pending',?,?,?,?,?,?,?,?,?)""",
            (approval_id, device_id, _pack_sensitive_list(commands), utcnow(),
             _pack_sensitive_list(rollback_commands), verify_command, expected_output_contains,
             rollback_after_seconds, json.dumps(expected_output_contains_all or []),
             json.dumps(expected_output_not_contains or []), json.dumps(expected_output_regex or []), requested_by),
        )


def approve(approval_id: str, approved_by: str | None = None, require_distinct: bool = False) -> bool:
    with connect() as con:
        if require_distinct:
            cur = con.execute(
                "UPDATE approvals SET status='approved', approved_at=?, approved_by=? "
                "WHERE id=? AND status='pending' AND requested_by IS NOT NULL AND requested_by<>?",
                (utcnow(), approved_by, approval_id, approved_by),
            )
        else:
            cur = con.execute(
                "UPDATE approvals SET status='approved', approved_at=?, approved_by=? WHERE id=? AND status='pending'",
                (utcnow(), approved_by, approval_id),
            )
        return cur.rowcount == 1


def get_approval(approval_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["commands"] = _unpack_sensitive_list(data.get("commands"))
        data["rollback_commands"] = _unpack_sensitive_list(data.get("rollback_commands"))
        for key in ("expected_output_contains_all", "expected_output_not_contains", "expected_output_regex"):
            data[key] = json.loads(data.get(key) or "[]")
        return data



def _insert_transaction(
    con: sqlite3.Connection, txid: str, approval: dict, snapshot_encrypted: str | None,
    apply_output: str, verify_output: str, due_at: str | None, initial_status: str,
    rollback_commands_override: list[str] | None = None,
    secret_values: list[str] | None = None,
) -> None:
    now = utcnow()
    con.execute(
        """INSERT INTO change_transactions(
          id,approval_id,device_id,snapshot_encrypted,status,rollback_due_at,
          rollback_commands,verify_command,expected_output_contains,
          apply_output,verify_output,created_at,updated_at,
          expected_output_contains_all,expected_output_not_contains,expected_output_regex,
          secret_values_encrypted
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (txid, approval["id"], approval["device_id"], snapshot_encrypted, initial_status, due_at,
         _pack_sensitive_list(rollback_commands_override if rollback_commands_override is not None
                              else approval["rollback_commands"]), approval["verify_command"],
         approval.get("expected_output_contains", ""), apply_output, verify_output,
         now, now, json.dumps(approval.get("expected_output_contains_all", [])),
         json.dumps(approval.get("expected_output_not_contains", [])),
         json.dumps(approval.get("expected_output_regex", [])),
         _pack_sensitive_list(secret_values or []) if secret_values else None),
    )


def create_transaction(
    txid: str, approval: dict, snapshot_encrypted: str | None,
    apply_output: str, verify_output: str, due_at: str | None,
    initial_status: str = "pending_confirmation",
    rollback_commands_override: list[str] | None = None,
    secret_values: list[str] | None = None,
) -> None:
    with connect() as con:
        _insert_transaction(
            con, txid, approval, snapshot_encrypted, apply_output, verify_output, due_at, initial_status,
            rollback_commands_override, secret_values,
        )


def consume_approval_and_create_transaction(
    txid: str, approval: dict, snapshot_encrypted: str | None,
    apply_output: str = "", verify_output: str = "", due_at: str | None = None,
    initial_status: str = "applying",
    rollback_commands_override: list[str] | None = None,
    secret_values: list[str] | None = None,
) -> bool:
    """Atomically consume one approved change and persist its transaction.

    If the insert fails, SQLite rolls back the approval status update as well.
    """
    with connect() as con:
        cur = con.execute(
            "UPDATE approvals SET status='consumed' WHERE id=? AND status='approved'",
            (approval["id"],),
        )
        if cur.rowcount != 1:
            return False
        _insert_transaction(
            con, txid, approval, snapshot_encrypted, apply_output, verify_output, due_at, initial_status,
            rollback_commands_override, secret_values,
        )
        return True


def update_transaction(txid: str, status: str, **fields: Any) -> None:
    allowed = {"rollback_output", "rollback_due_at", "apply_output", "verify_output", "rollback_by"}
    updates = {key: value for key, value in fields.items() if key in allowed}
    for output_key in ("rollback_output", "apply_output", "verify_output"):
        if isinstance(updates.get(output_key), str):
            from app.security.redaction import redact_text
            updates[output_key] = redact_text(updates[output_key])
    updates["status"] = status
    updates["updated_at"] = utcnow()
    sets = ", ".join(f"{key}=?" for key in updates)
    with connect() as con:
        con.execute(f"UPDATE change_transactions SET {sets} WHERE id=?", (*updates.values(), txid))


def finalize_apply_transaction(txid: str, apply_output: str, verify_output: str, due_at: str) -> bool:
    """Move a durably recorded in-flight change into its confirmation window."""
    with connect() as con:
        cur = con.execute(
            """UPDATE change_transactions
               SET status='pending_confirmation',rollback_due_at=?,apply_output=?,verify_output=?,updated_at=?
               WHERE id=? AND status='applying'""",
            (due_at, redact_text(apply_output), redact_text(verify_output), utcnow(), txid),
        )
        return cur.rowcount == 1


def claim_interrupted_applications(age_seconds: int = 0) -> list[str]:
    """Reserve stale `applying` transactions; age guard protects live peer MCP processes."""
    from datetime import timedelta
    claimed: list[str] = []
    now = utcnow()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max(0, age_seconds))).isoformat()
    with connect() as con:
        rows = con.execute(
            "SELECT id FROM change_transactions WHERE status='applying' AND updated_at<?", (cutoff,)
        ).fetchall()
        for row in rows:
            cur = con.execute(
                "UPDATE change_transactions SET status='rolling_back',updated_at=? WHERE id=? AND status='applying'",
                (now, row["id"]),
            )
            if cur.rowcount == 1:
                claimed.append(row["id"])
    return claimed



def complete_rollback_transaction(txid: str, status: str, output: str, rollback_by: str) -> bool:
    """Finalize only a rollback currently owned in the `rolling_back` state."""
    if status not in ("rolled_back", "rollback_failed"):
        raise ValueError("非法回滚终态")
    from app.security.redaction import redact_text
    with connect() as con:
        cur = con.execute(
            "UPDATE change_transactions SET status=?,rollback_output=?,rollback_due_at=NULL,rollback_by=?,updated_at=? "
            "WHERE id=? AND status='rolling_back'",
            (status, redact_text(output), rollback_by, utcnow(), txid),
        )
        return cur.rowcount == 1


def mark_stale_rollbacks_failed(age_seconds: int = 600) -> int:
    """Mark long-stuck rolling_back transactions as uncertain; do not replay them.

    This is designed for multiple Harness stdio child processes sharing one DB:
    a newly claimed rollback is left alone, while a rollback that has not updated
    its state for the safety window requires human device-side verification.
    """
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max(60, age_seconds))).isoformat()
    now = utcnow()
    with connect() as con:
        cur = con.execute(
            "UPDATE change_transactions SET status='rollback_failed',rollback_due_at=NULL, "
            "rollback_output=COALESCE(rollback_output,'') || ?,updated_at=? "
            "WHERE status='rolling_back' AND updated_at<?",
            ("\n[RECOVERY] 回滚状态超过安全等待窗口仍未完成；未自动重放，请人工核查设备实际配置。", now, cutoff),
        )
        return cur.rowcount


def get_transaction(txid: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM change_transactions WHERE id=?", (txid,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["rollback_commands"] = _unpack_sensitive_list(data["rollback_commands"])
        data["secret_values"] = _unpack_sensitive_list(data.get("secret_values_encrypted"))
        data.pop("secret_values_encrypted", None)
        for key in ("expected_output_contains_all", "expected_output_not_contains", "expected_output_regex"):
            data[key] = json.loads(data.get(key) or "[]")
        return data


def confirm_transaction(txid: str, confirmed_by: str | None = None) -> bool:
    with connect() as con:
        cur = con.execute(
            """UPDATE change_transactions SET status='confirmed', rollback_due_at=NULL, confirmed_by=?, updated_at=?
               WHERE id=? AND status='pending_confirmation'""",
            (confirmed_by, utcnow(), txid),
        )
        return cur.rowcount == 1


def claim_manual_rollback(txid: str) -> bool:
    """Atomically reserve a pending transaction for manual rollback.

    This closes the race where a manual rollback and the timer worker could both
    observe `pending_confirmation` and execute the same rollback commands.
    """
    with connect() as con:
        cur = con.execute(
            """UPDATE change_transactions SET status='rolling_back', updated_at=?
               WHERE id=? AND status='pending_confirmation'""",
            (utcnow(), txid),
        )
        return cur.rowcount == 1


def claim_due_rollbacks(now_iso: str | None = None) -> list[str]:
    now_iso = now_iso or utcnow()
    claimed: list[str] = []
    with connect() as con:
        rows = con.execute(
            """SELECT id FROM change_transactions
               WHERE status='pending_confirmation' AND rollback_due_at IS NOT NULL
               AND rollback_due_at <= ?""", (now_iso,),
        ).fetchall()
        for row in rows:
            cur = con.execute(
                """UPDATE change_transactions SET status='rolling_back', updated_at=?
                   WHERE id=? AND status='pending_confirmation'""",
                (utcnow(), row["id"]),
            )
            if cur.rowcount == 1:
                claimed.append(row["id"])
    return claimed



def recent_audit(after_id: int = 0, limit: int = 100) -> list[dict]:
    """Return a bounded audit range for diagnostics and troubleshooting."""
    limit = max(1, min(int(limit), 200))
    with connect() as con:
        rows = con.execute(
            "SELECT id,actor,action,device_id,details,created_at FROM audit "
            "WHERE id>? ORDER BY id ASC LIMIT ?", (int(after_id), limit),
        ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["details"] = redact_value(json.loads(item["details"]))
            result.append(item)
        return result


# ---- Durable change-job progress (used by Harness clients that do not render MCP progress). ----
def create_change_job(job_id: str, approval_id: str) -> None:
    now = utcnow()
    with connect() as con:
        con.execute(
            "INSERT INTO change_jobs(id,approval_id,status,progress,message,events,created_at,updated_at) "
            "VALUES(?,?,'queued',0,'等待执行','[]',?,?)",
            (job_id, approval_id, now, now),
        )


def append_change_job_progress(approval_id: str, progress: int, message: str) -> None:
    now = utcnow()
    progress = max(0, min(100, int(progress)))
    with connect() as con:
        row = con.execute("SELECT events FROM change_jobs WHERE approval_id=?", (approval_id,)).fetchone()
        if not row:
            return
        events = json.loads(row["events"] or "[]")
        events.append({"progress": progress, "message": message, "at": now})
        events = events[-100:]
        con.execute(
            "UPDATE change_jobs SET status='running',progress=?,message=?,events=?,updated_at=? WHERE approval_id=?",
            (progress, message, json.dumps(events, ensure_ascii=False), now, approval_id),
        )


def finish_change_job(approval_id: str, result: dict | None = None, error: str | None = None) -> None:
    now = utcnow()
    status = "completed" if result is not None else "failed"
    with connect() as con:
        con.execute(
            "UPDATE change_jobs SET status=?,progress=100,message=?,result=?,error=?,updated_at=? WHERE approval_id=?",
            (status, "执行流程结束" if result is not None else "执行线程异常退出",
             json.dumps(redact_value(result), ensure_ascii=False) if result is not None else None,
             redact_value(error), now, approval_id),
        )


def get_change_job(approval_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM change_jobs WHERE approval_id=?", (approval_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["events"] = json.loads(data.get("events") or "[]")
        data["result"] = json.loads(data["result"]) if data.get("result") else None
        return data


def recover_interrupted_change_jobs(age_seconds: int = 0) -> int:
    """Mark stale jobs interrupted; age guard avoids touching an active peer process job."""
    from datetime import timedelta
    now = utcnow()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max(0, age_seconds))).isoformat()
    count = 0
    with connect() as con:
        rows = con.execute(
            "SELECT approval_id,events FROM change_jobs WHERE status IN ('queued','running') AND updated_at<?",
            (cutoff,),
        ).fetchall()
        for row in rows:
            events = json.loads(row["events"] or "[]")
            events.append({
                "progress": 100,
                "message": "MCP 进程在任务结束前退出；请核对事务状态和设备实际配置，禁止自动重放。",
                "at": now,
            })
            cur = con.execute(
                "UPDATE change_jobs SET status='interrupted',progress=100,message=?,events=?,error=?,updated_at=? "
                "WHERE approval_id=? AND status IN ('queued','running')",
                ("进程中断，等待人工核查", json.dumps(events[-100:], ensure_ascii=False),
                 "MCP 进程退出导致任务状态中断；请检查 change_transactions、audit 和设备配置。",
                 now, row["approval_id"]),
            )
            count += cur.rowcount
    return count

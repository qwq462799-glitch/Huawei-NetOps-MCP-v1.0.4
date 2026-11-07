from app import storage

def test_database_initializes(tmp_path, monkeypatch):
    # storage path由 DATABASE_URL 设置；此处验证初始化表结构。
    from app.config import settings
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/test.db")
    storage.init_db()
    with storage.connect() as con:
        names = {r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"devices", "approvals", "audit"}.issubset(names)


def test_recent_audit_is_incremental(tmp_path, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path}/audit.db")
    storage.init_db()
    storage.audit("mcp-client", "command.execute", "sw1", {"command": "display version"})
    rows = storage.recent_audit(after_id=0, limit=10)
    assert len(rows) == 1
    assert rows[0]["action"] == "command.execute"
    assert rows[0]["details"]["command"] == "display version"
    assert storage.recent_audit(after_id=rows[0]["id"], limit=10) == []

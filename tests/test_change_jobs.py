import time

from app import storage
from app.config import settings
from app.services import change_jobs


def test_async_apply_job_records_progress_and_final_result(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{tmp_path / 'async.db'}")
    storage.init_db()
    storage.create_approval("a-async", "sw1", ["vlan 1"], ["undo vlan 1"],
                            "display vlan", "VLAN", 300)
    storage.approve("a-async")

    def fake_apply(approval_id, progress=None):
        progress(20, "读取快照")
        progress(65, "配置验证")
        return {"success": True, "status": "pending_confirmation", "transaction_id": "tx-a"}

    monkeypatch.setattr(change_jobs, "apply_change", fake_apply)
    started = change_jobs.start_apply_job("a-async")
    assert started["success"] is True
    deadline = time.time() + 3
    while time.time() < deadline:
        status = change_jobs.get_apply_job("a-async")
        if status.get("status") == "completed":
            break
        time.sleep(0.02)
    assert status["status"] == "completed"
    assert status["progress"] == 100
    assert status["result"]["transaction_id"] == "tx-a"
    assert any(event["message"] == "配置验证" for event in status["events"])

    duplicate = change_jobs.start_apply_job("a-async")
    assert duplicate["success"] is False
    assert duplicate["job_id"] == started["job_id"]

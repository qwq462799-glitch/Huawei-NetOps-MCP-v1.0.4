"""Background apply jobs with durable progress for MCP clients that hide progress notifications."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
import uuid

from app.services.device_service import apply_change
from app.storage import (
    append_change_job_progress, create_change_job, finish_change_job,
    get_approval, get_change_job,
)

log = logging.getLogger(__name__)
_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="netops-change")


def _run_apply_job(approval_id: str) -> None:
    try:
        result = apply_change(
            approval_id,
            progress=lambda percent, message: append_change_job_progress(approval_id, percent, message),
        )
        finish_change_job(approval_id, result=result)
    except Exception as exc:
        log.exception("配置变更后台任务失败，approval_id=%s", approval_id)
        finish_change_job(approval_id, error=str(exc))


def start_apply_job(approval_id: str) -> dict:
    """Queue one approved change; use get_apply_job() to query persisted progress."""
    approval = get_approval(approval_id)
    if not approval or approval.get("status") != "approved":
        raise PermissionError("审批不存在或尚未批准")
    job_id = str(uuid.uuid4())
    try:
        create_change_job(job_id, approval_id)
    except Exception as exc:
        existing = get_change_job(approval_id)
        if existing:
            return {
                "success": False,
                "approval_id": approval_id,
                "job_id": existing["id"],
                "status": existing["status"],
                "error": "该审批单已创建过后台任务；请查询已有任务，不能重复提交。",
            }
        raise exc
    append_change_job_progress(approval_id, 1, "后台任务已排队")
    _EXECUTOR.submit(_run_apply_job, approval_id)
    return {
        "success": True,
        "approval_id": approval_id,
        "job_id": job_id,
        "status": "queued",
        "message": "任务已启动。Harness 未展示 MCP 进度通知时，可重复调用 config_apply_progress 查询实时阶段。",
    }


def get_apply_job(approval_id: str) -> dict:
    job = get_change_job(approval_id)
    if not job:
        return {"success": False, "approval_id": approval_id, "error": "未找到该审批单的后台执行任务"}
    return {
        "success": True,
        "job_id": job["id"],
        "approval_id": job["approval_id"],
        "status": job["status"],
        "progress": job["progress"],
        "message": job["message"],
        "events": job["events"],
        "result": job["result"],
        "error": job["error"],
        "updated_at": job["updated_at"],
    }

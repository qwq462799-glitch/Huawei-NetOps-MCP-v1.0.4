"""Single-leader rollback scheduler shared safely by multiple stdio MCP processes."""
from __future__ import annotations

import logging
import threading
import time

from filelock import FileLock, Timeout

from app.storage import worker_lock_path, mark_stale_rollbacks_failed
from app.services.device_service import process_due_rollbacks, recover_interrupted_applications
from app.storage import recover_interrupted_change_jobs

log = logging.getLogger(__name__)
# A generous stale threshold avoids classifying a legitimate long-running CLI
# apply/rollback as crashed; uncertain operations still fail closed after 30 min.
STALE_OPERATION_SECONDS = 1800


def _recover_on_leader_start() -> None:
    # Only the process that owns the DB-level worker lock may classify interrupted
    # jobs or recover `applying` transactions. Followers must not mistake another
    # live process's `rolling_back` operation for a crashed one.
    jobs = recover_interrupted_change_jobs(age_seconds=STALE_OPERATION_SECONDS)
    if jobs:
        log.warning("检测到 %s 个上次中断的后台任务，请核查事务与设备配置。", jobs)
    interrupted = recover_interrupted_applications(age_seconds=STALE_OPERATION_SECONDS)
    if interrupted:
        log.warning("已处理 %s 个中断中的配置事务；请核查设备实际状态。", len(interrupted))


def start_rollback_worker(poll_seconds: int = 2):
    """Elect one SQLite-backed scheduler leader; followers retry after leader exit."""
    def run():
        lock = None
        last_stale_scan = 0.0
        while True:
            if lock is None:
                candidate = FileLock(worker_lock_path(), timeout=0)
                try:
                    candidate.acquire()
                    lock = candidate
                    log.info("本 MCP 进程已取得回滚调度主节点锁。")
                    try:
                        _recover_on_leader_start()
                    except Exception:
                        log.exception("回滚调度主节点启动恢复异常")
                except Timeout:
                    log.debug("其他 MCP 进程正在执行回滚调度；当前进程作为 follower 等待。")
                    time.sleep(max(1, poll_seconds))
                    continue
                except Exception:
                    log.exception("获取回滚调度锁失败")
                    time.sleep(max(1, poll_seconds))
                    continue
            try:
                now = time.monotonic()
                if now - last_stale_scan >= 60:
                    stale_jobs = recover_interrupted_change_jobs(age_seconds=STALE_OPERATION_SECONDS)
                    if stale_jobs:
                        log.warning("检测到 %s 个超过 30 分钟无进度的后台任务，已标记中断。", stale_jobs)
                    changed = mark_stale_rollbacks_failed(STALE_OPERATION_SECONDS)
                    if changed:
                        log.error("有 %s 个回滚事务超时未完成，已标记 rollback_failed，需人工核查。", changed)
                    last_stale_scan = now
                results = process_due_rollbacks()
                for result in results:
                    log.warning("自动回滚处理结果：%s", result)
            except Exception:
                log.exception("自动回滚工作线程发生异常")
            time.sleep(max(1, poll_seconds))

    thread = threading.Thread(target=run, name="netops-rollback-worker", daemon=True)
    thread.start()
    return thread

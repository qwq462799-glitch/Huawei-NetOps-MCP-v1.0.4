"""Persistent, process-local network CLI sessions for Harness terminal tools."""
from __future__ import annotations

import atexit
import threading
import time
import uuid
from dataclasses import dataclass, field

from app.drivers.factory import get_driver
from app.security.policy import validate_command
from app.security.device_output import detect_device_error
from app.security.redaction import redact_text
from app.security.rbac import current_principal
from app.services.device_service import _runtime_device
from app.storage import audit, get_device

SESSION_TTL_SECONDS = 60 * 60
MAX_TERMINAL_SESSIONS = 16
MAX_SESSIONS_PER_DEVICE = 4


@dataclass
class ActiveTerminalSession:
    session_id: str
    device_id: str
    transport: str
    opened_at: float
    last_used: float
    connection: object
    owner_id: str
    lock: threading.RLock = field(default_factory=threading.RLock)


_SESSIONS: dict[str, ActiveTerminalSession] = {}
_SESSIONS_LOCK = threading.RLock()
_OPENING_TOTAL = 0
_OPENING_BY_DEVICE: dict[str, int] = {}


def _close_expired(now: float | None = None) -> None:
    now = now or time.monotonic()
    expired: list[ActiveTerminalSession] = []
    with _SESSIONS_LOCK:
        for key, session in list(_SESSIONS.items()):
            if now - session.last_used > SESSION_TTL_SECONDS:
                expired.append(_SESSIONS.pop(key))
    for session in expired:
        try:
            with session.lock:
                session.connection.close()
        except Exception:
            pass
        audit(session.owner_id, "terminal.session.expired", session.device_id,
              {"session_id": session.session_id})


def connect_terminal(device_id: str) -> dict:
    """Open and retain one SSH/Telnet CLI connection in this MCP process."""
    _close_expired()
    device = get_device(device_id)
    if not device:
        return {"success": False, "error": f"设备不存在：{device_id}"}
    if not device.get("enabled", True):
        return {"success": False, "error": "设备已禁用"}

    global _OPENING_TOTAL
    with _SESSIONS_LOCK:
        active_for_device = sum(1 for session in _SESSIONS.values() if session.device_id == device_id)
        opening_for_device = _OPENING_BY_DEVICE.get(device_id, 0)
        if len(_SESSIONS) + _OPENING_TOTAL >= MAX_TERMINAL_SESSIONS:
            return {"success": False, "device_id": device_id,
                    "error": f"当前 MCP 进程最多允许 {MAX_TERMINAL_SESSIONS} 个终端会话。"}
        if active_for_device + opening_for_device >= MAX_SESSIONS_PER_DEVICE:
            return {"success": False, "device_id": device_id,
                    "error": f"设备 {device_id} 最多允许 {MAX_SESSIONS_PER_DEVICE} 个并发终端会话。"}
        _OPENING_TOTAL += 1
        _OPENING_BY_DEVICE[device_id] = opening_for_device + 1

    session = None
    reservation_active = True
    try:
        runtime = _runtime_device(device)
        driver = get_driver(runtime)
        if not hasattr(driver, "open_interactive_session"):
            raise RuntimeError("当前驱动不支持持久交互会话")
        session = driver.open_interactive_session(runtime)
        sid = uuid.uuid4().hex
        now = time.monotonic()
        owner_id = current_principal()["id"]
        item = ActiveTerminalSession(
            session_id=sid,
            device_id=device_id,
            transport=str(runtime.get("connection", "ssh")),
            opened_at=now,
            last_used=now,
            connection=session,
            owner_id=owner_id,
        )
        with _SESSIONS_LOCK:
            _OPENING_TOTAL -= 1
            remaining = _OPENING_BY_DEVICE.get(device_id, 1) - 1
            if remaining > 0:
                _OPENING_BY_DEVICE[device_id] = remaining
            else:
                _OPENING_BY_DEVICE.pop(device_id, None)
            reservation_active = False
            _SESSIONS[sid] = item
        audit(owner_id, "terminal.session.open", device_id,
              {"session_id": sid, "transport": item.transport})
        return {
            "success": True,
            "session_id": sid,
            "device_id": device_id,
            "transport": item.transport,
            "message": f"已连接 {device_id}，持久 CLI 会话已建立。",
        }
    except Exception as exc:
        if reservation_active:
            with _SESSIONS_LOCK:
                _OPENING_TOTAL = max(0, _OPENING_TOTAL - 1)
                remaining = _OPENING_BY_DEVICE.get(device_id, 1) - 1
                if remaining > 0:
                    _OPENING_BY_DEVICE[device_id] = remaining
                else:
                    _OPENING_BY_DEVICE.pop(device_id, None)
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
        actor = current_principal()["id"]
        audit(actor, "terminal.session.open_failed", device_id,
              {"error": str(exc)})
        return {"success": False, "device_id": device_id, "error": redact_text(str(exc))}


def execute_terminal(session_id: str, command: str) -> dict:
    """Execute one policy-approved read-only command on an existing session."""
    _close_expired()
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(session_id)
    if not session:
        return {"success": False, "error": "终端会话不存在或已过期，请重新 connect。"}

    try:
        validate_command(command, allow_write=False)
    except Exception as exc:
        return {
            "success": False,
            "tool_success": False,
            "device_error": False,
            "device_id": session.device_id,
            "session_id": session_id,
            "command": redact_text(command),
            "error": redact_text(str(exc)),
            "next_step": "配置类写命令必须通过 config_request_approval、config_approve、config_apply_approved 审批流程执行。",
        }

    started = time.perf_counter()
    try:
        with session.lock:
            output = session.connection.execute_read(command)
            session.last_used = time.monotonic()
        cli_error = detect_device_error(output)
        success = cli_error is None
        duration_ms = int((time.perf_counter() - started) * 1000)
        audit(current_principal()["id"], "terminal.command", session.device_id, {
            "session_id": session_id,
            "command": command,
            "success": success,
            "device_error": bool(cli_error),
            "device_error_line": cli_error["line"] if cli_error else None,
            "output_length": len(output),
            "duration_ms": duration_ms,
        })
        result = {
            "success": success,
            "tool_success": True,
            "device_error": bool(cli_error),
            "device_id": session.device_id,
            "session_id": session_id,
            "command": redact_text(command),
            "output": redact_text(output),
            "duration_ms": duration_ms,
            "status": "completed" if success else "device_error",
        }
        if cli_error:
            result["error"] = "设备返回 CLI 命令错误；请检查命令是否适用于当前设备型号/系统版本。"
            result["device_error_line"] = cli_error["line"]
        return result
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        audit(current_principal()["id"], "terminal.command", session.device_id, {
            "session_id": session_id,
            "command": command,
            "success": False,
            "error": str(exc),
            "duration_ms": duration_ms,
        })
        return {
            "success": False,
            "tool_success": False,
            "device_error": False,
            "device_id": session.device_id,
            "session_id": session_id,
            "command": redact_text(command),
            "error": redact_text(str(exc)),
            "duration_ms": duration_ms,
            "status": "failed",
        }


def disconnect_terminal(session_id: str) -> dict:
    with _SESSIONS_LOCK:
        session = _SESSIONS.pop(session_id, None)
    if not session:
        return {"success": False, "session_id": session_id, "error": "终端会话不存在"}
    try:
        with session.lock:
            session.connection.close()
        audit(current_principal()["id"], "terminal.session.close", session.device_id,
              {"session_id": session_id})
        return {"success": True, "session_id": session_id, "device_id": session.device_id}
    except Exception as exc:
        audit(current_principal()["id"], "terminal.session.close_failed", session.device_id,
              {"session_id": session_id, "error": str(exc)})
        return {"success": False, "session_id": session_id, "error": redact_text(str(exc))}


def list_terminal_sessions() -> list[dict]:
    _close_expired()
    now = time.monotonic()
    with _SESSIONS_LOCK:
        return [
            {
                "session_id": s.session_id,
                "device_id": s.device_id,
                "transport": s.transport,
                "idle_seconds": max(0, int(now - s.last_used)),
            }
            for s in _SESSIONS.values()
        ]


def close_all_terminal_sessions() -> None:
    with _SESSIONS_LOCK:
        sessions = list(_SESSIONS.values())
        _SESSIONS.clear()
    for session in sessions:
        try:
            with session.lock:
                session.connection.close()
        except Exception:
            pass


# Close long-lived device sockets when the Harness-managed MCP child exits.
atexit.register(close_all_terminal_sessions)

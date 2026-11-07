#!/usr/bin/env python3
"""Create a private local .env/key and initialize the SQLite database safely."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
EXAMPLE_FILE = ROOT / ".env.example"


def _write_env_atomically(root: Path, env_file: Path, content: str) -> None:
    """Replace .env atomically; on POSIX create it with owner-only permissions."""
    fd, temp_name = tempfile.mkstemp(prefix=".env.", suffix=".tmp", dir=root)
    temp_path = Path(temp_name)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, env_file)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        temp_path.unlink(missing_ok=True)
        raise
    if os.name != "nt":
        env_file.chmod(0o600)


def _database_file_from_env(root: Path, content: str) -> Path | None:
    matches = list(re.finditer(r"(?m)^DATABASE_URL[ \t]*=[ \t]*(.*?)[ \t]*$", content))
    if len(matches) > 1:
        raise RuntimeError(".env 中 DATABASE_URL 重复定义，请先修正配置。")
    file_url = matches[0].group(1).strip().strip('"').strip("'") if matches else "sqlite:///./data/netops.db"
    process_url = os.environ.get("DATABASE_URL", "").strip()
    # Match Pydantic Settings precedence: the process environment overrides .env.
    # We must inspect the exact database path the MCP process will open.
    url = process_url or file_url
    if not url.startswith("sqlite:///"):
        return None
    raw_path = url.replace("sqlite:///", "", 1)
    path = Path(raw_path).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def _ensure_env(root: Path = ROOT) -> None:
    root = root.resolve()
    env_file = root / ".env"
    example_file = root / ".env.example"
    if env_file.is_symlink():
        raise RuntimeError("项目 .env 不能是符号链接；为避免覆盖外部文件，初始化已停止。")
    if env_file.exists() and not env_file.is_file():
        raise RuntimeError("项目 .env 路径不是普通文件，初始化已停止。")
    if not env_file.exists():
        if not example_file.is_file():
            raise RuntimeError("缺少 .env.example，无法初始化运行配置。")
        try:
            fd = os.open(
                env_file,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(example_file.read_text(encoding="utf-8"))
        except FileExistsError:
            # A second installer may have won the create race. Validate the file below.
            pass

    content = env_file.read_text(encoding="utf-8")
    key_matches = list(re.finditer(r"(?m)^CREDENTIAL_ENCRYPTION_KEY[ \t]*=[ \t]*(.*)$", content))
    if len(key_matches) > 1:
        raise RuntimeError(".env 中 CREDENTIAL_ENCRYPTION_KEY 重复定义；请只保留一行，避免密钥来源歧义。")
    match = key_matches[0] if key_matches else None
    file_key = match.group(1).strip().strip('"').strip("'") if match else ""
    process_key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY", "").strip()
    if process_key and file_key and process_key != file_key:
        raise RuntimeError(
            "进程环境 CREDENTIAL_ENCRYPTION_KEY 与项目 .env 不一致；为避免密钥来源歧义，已停止初始化。"
        )
    key_value = process_key or file_key
    if not key_value:
        db_file = _database_file_from_env(root, content)
        if db_file and any(Path(str(db_file) + suffix).exists() for suffix in ("", "-wal", "-shm")):
            raise RuntimeError(
                "检测到已有 SQLite 数据库，但没有可用的 CREDENTIAL_ENCRYPTION_KEY。"
                "为避免生成新密钥导致旧设备凭证/快照无法解密，已停止初始化；请恢复原 .env/密钥后重试。"
            )
        key_value = Fernet.generate_key().decode("ascii")
    # Validate any process/.env key before writing it or opening the database.
    try:
        Fernet(key_value.encode("ascii"))
    except Exception as exc:
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEY 格式无效；不会自动覆盖已有密钥。"
        ) from exc
    if not file_key or file_key != key_value:
        if match:
            content = content[:match.start(1)] + key_value + content[match.end(1):]
        else:
            content = content.rstrip() + f"\nCREDENTIAL_ENCRYPTION_KEY={key_value}\n"
        _write_env_atomically(root, env_file, content)
    elif os.name != "nt":
        env_file.chmod(0o600)


def main() -> None:
    os.chdir(ROOT)
    _ensure_env(ROOT)

    # Import only after .env exists: Settings reads the project-anchored env file.
    from app.storage import _db_path, init_db

    db_path = _db_path()
    if os.name != "nt" and db_path.parent == (ROOT / "data").resolve():
        db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        db_path.parent.chmod(0o700)
    init_db()

    if os.name != "nt":
        for protected_file in (
            db_path,
            Path(str(db_path) + "-wal"),
            Path(str(db_path) + "-shm"),
            Path(str(db_path) + ".schema.lock"),
        ):
            if protected_file.exists():
                protected_file.chmod(0o600)

    print("[OK] 环境文件已就绪（加密密钥自动生成，未在终端回显）")
    print("[OK] SQLite 数据库已初始化")
    print("[OK] 本地 .env、数据库和数据库目录已应用最小权限")


if __name__ == "__main__":
    main()

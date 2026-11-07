from __future__ import annotations

import importlib.util
import os
import platform
import sys
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def doctor() -> int:
    root = _project_root()
    os.chdir(root)
    print("Huawei NetOps MCP - 环境检查")
    print(f"操作系统：{platform.platform()}")
    print(f"Python：{sys.version.split()[0]}")
    ok = True
    if not ((3, 11) <= sys.version_info[:2] < (3, 13)):
        print("[FAIL] 需要 Python 3.11 或 3.12（Python 3.13 暂不在支持范围）")
        ok = False
    else:
        print("[OK] Python 版本兼容")
    env_file = root / ".env"
    if env_file.exists():
        print("[OK] .env 存在")
    else:
        print("[FAIL] .env 不存在；请运行项目根目录的一键启动脚本")
        ok = False
    for module in ("fastmcp", "netmiko", "cryptography", "yaml", "filelock", "pydantic_settings"):
        present = importlib.util.find_spec(module) is not None
        print(f"[{ 'OK' if present else 'FAIL' }] 依赖：{module}")
        ok = ok and present
    try:
        from cryptography.fernet import Fernet
        from app.config import Settings
        config = Settings()
        if not config.credential_encryption_key:
            raise ValueError("CREDENTIAL_ENCRYPTION_KEY 为空；请重新运行一键初始化")
        Fernet(config.credential_encryption_key.encode("ascii"))
        print("[OK] Fernet 加密密钥格式有效（密钥不回显）")
    except Exception as exc:
        print(f"[FAIL] 加密密钥检查失败：{type(exc).__name__}: {exc}")
        ok = False
    try:
        from app.security.rbac import current_principal, dual_approval_required
        principal = current_principal()
        print(f"[OK] 当前 MCP 身份：{principal['id']} / {principal['role']}")
        print(f"[{'OK' if dual_approval_required() else 'WARN'}] 双人审批：{'已启用' if dual_approval_required() else '未启用'}")
    except Exception as exc:
        print(f"[FAIL] RBAC 身份配置无效：{exc}")
        ok = False
    try:
        from app.storage import init_db
        init_db()
        print("[OK] SQLite 数据库可用（已执行非破坏性 schema 迁移）")
    except Exception as exc:
        print(f"[FAIL] 数据库初始化失败：{exc}")
        ok = False
    if not ok:
        return 1
    print("检查完成：DeepSeek Harness 可以通过 stdio 启动 MCP。")
    return 0


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="netops", description="Huawei NetOps MCP environment checker")
    parser.add_argument("action", choices=("doctor",), help="doctor：检查运行依赖、密钥、身份和数据库")
    args = parser.parse_args()
    if args.action == "doctor":
        raise SystemExit(doctor())


if __name__ == "__main__":
    main()

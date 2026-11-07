import os
from cryptography.fernet import Fernet
from dotenv import dotenv_values
from app.config import PROJECT_ENV_FILE, settings

def _fernet():
    key = settings.credential_encryption_key
    if not key:
        raise RuntimeError("未配置 CREDENTIAL_ENCRYPTION_KEY。请先生成 Fernet 密钥并写入 .env。")
    return Fernet(key.encode())

def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()

def decrypt_secret(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()

def resolve_password(device: dict) -> str:
    env_name = device.get("password_env")
    if env_name:
        # Prefer the protected MCP process environment; also support the project
        # .env file so password_env works consistently in Harness stdio profiles.
        value = os.getenv(env_name)
        if not value:
            try:
                value = dotenv_values(PROJECT_ENV_FILE).get(env_name)
            except Exception:
                value = None
        if not value:
            raise RuntimeError(f"缺少设备密码环境变量：{env_name}")
        if any(char in value for char in ("\n", "\r", "\x00")):
            raise RuntimeError(f"设备密码环境变量 {env_name} 包含换行或空字符")
        return value
    password = device.get("password")
    if not password:
        raise RuntimeError("设备未配置密码")
    return password

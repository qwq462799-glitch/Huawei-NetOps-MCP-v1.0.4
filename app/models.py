from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Vendor = Literal["huawei", "h3c", "cisco"]
Connection = Literal["ssh", "telnet"]


class Device(BaseModel):
    """Validated network-device record accepted by the MCP device_add tool."""

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    name: str = Field(min_length=1, max_length=128)
    vendor: Vendor
    platform: str = Field(min_length=1, max_length=64)
    connection: Connection = "ssh"
    simulator: Literal["ensp", "ensp_pro"] | None = None
    host: str = Field(min_length=1, max_length=253)
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=128)
    password: str | None = Field(default=None, repr=False, max_length=1024)
    password_env: str | None = Field(default=None, max_length=128)
    enabled: bool = True
    environment: str = Field(default="lab", min_length=1, max_length=32)

    @model_validator(mode="before")
    @classmethod
    def choose_simulator_transport_default(cls, value):
        # Classic eNSP commonly exposes a Telnet console; eNSP Pro and physical
        # devices default to SSH. Preserve an explicitly supplied transport.
        if isinstance(value, dict) and "connection" not in value:
            value = dict(value)
            if value.get("simulator") == "ensp":
                value["connection"] = "telnet"
        return value

    @field_validator("name", "platform", "username", "environment")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("字段不能为空或包含控制字符")
        return value

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        value = value.strip()
        # DNS names, IPv4, IPv6 and IPv6 zone IDs are supported; whitespace,
        # path separators and shell/CLI delimiters are never valid host text.
        if not value or not re.fullmatch(r"[A-Za-z0-9_.:%-]+", value):
            raise ValueError("host 必须是有效的 IP 地址或主机名，不能包含空白或命令分隔符")
        if value.startswith(".") or value.endswith(".") or ".." in value:
            raise ValueError("host 主机名格式不合法")
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str | None) -> str | None:
        if value is not None:
            if not value or any(char in value for char in ("\n", "\r", "\x00")):
                raise ValueError("password 不能为空或包含换行/空字符")
        return value

    @field_validator("password_env")
    @classmethod
    def validate_password_env(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", value):
            raise ValueError("password_env 必须是合法的环境变量名称")
        return value

    @model_validator(mode="after")
    def require_one_credential_source(self):
        if bool(self.password) == bool(self.password_env):
            raise ValueError("必须且只能提供 password 或 password_env 其中一种凭证来源")
        return self


class CommandResult(BaseModel):
    success: bool
    device_id: str
    command: str
    output: str = ""
    error: str | None = None
    duration_ms: int = 0

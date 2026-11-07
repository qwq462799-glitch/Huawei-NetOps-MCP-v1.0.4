from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    """Runtime settings loaded from the protected MCP process environment and project .env."""

    model_config = SettingsConfigDict(env_file=PROJECT_ENV_FILE, extra="ignore")

    database_url: str = "sqlite:///./data/netops.db"
    credential_encryption_key: str = ""
    log_level: str = "INFO"
    # Identity is bound by the protected stdio process environment, never by tool arguments.
    operator_id: str = Field(default="local-viewer", validation_alias="NETOPS_OPERATOR_ID")
    operator_role: str = Field(default="viewer", validation_alias="NETOPS_OPERATOR_ROLE")
    require_dual_approval: bool = Field(default=True, validation_alias="NETOPS_REQUIRE_DUAL_APPROVAL")


settings = Settings()

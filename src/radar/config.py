"""Typed application configuration."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    """Configuration loaded from environment variables and `.env.local`."""

    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        env_prefix="RADAR_",
        extra="ignore",
    )

    environment: Environment = "development"
    database_url: SecretStr
    public_origin: str = "http://127.0.0.1:8000"
    frontend_directory: Path = Path("frontend/dist")
    session_idle_seconds: int = Field(default=43_200, ge=60, le=604_800)
    session_absolute_seconds: int = Field(default=604_800, ge=300, le=2_592_000)
    sirene_api_key: SecretStr | None = None
    datatourisme_api_key: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def require_psycopg_driver(cls, value: SecretStr) -> SecretStr:
        """Reject ambiguous or unsupported database drivers at startup."""

        if not value.get_secret_value().startswith("postgresql+psycopg://"):
            msg = "database URL must use the postgresql+psycopg driver"
            raise ValueError(msg)
        return value

    @field_validator("public_origin")
    @classmethod
    def require_exact_http_origin(cls, value: str) -> str:
        """Accept one HTTP origin without credentials, path, query or fragment."""

        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            msg = "public origin must contain only an http(s) scheme and authority"
            raise ValueError(msg)
        return f"{parsed.scheme}://{parsed.netloc}"

    @model_validator(mode="after")
    def validate_security_timeouts(self) -> "Settings":
        """Reject unsafe production transport and incoherent session lifetimes."""

        if self.environment == "production" and not self.public_origin.startswith("https://"):
            msg = "production public origin must use https"
            raise ValueError(msg)
        if self.session_idle_seconds > self.session_absolute_seconds:
            msg = "session idle timeout cannot exceed the absolute timeout"
            raise ValueError(msg)
        return self

    @property
    def session_cookie_name(self) -> str:
        """Use the browser-enforced Host prefix only over production HTTPS."""

        return "__Host-radar_session" if self.environment == "production" else "radar_session"

    @property
    def csrf_cookie_name(self) -> str:
        """Name the readable CSRF cookie consistently with the session cookie."""

        return "__Host-radar_csrf" if self.environment == "production" else "radar_csrf"

    @property
    def secure_cookies(self) -> bool:
        """Require HTTPS transport for production cookies."""

        return self.environment == "production"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache the immutable process configuration."""

    return Settings()

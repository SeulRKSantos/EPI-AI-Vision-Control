"""Application settings, loaded from environment variables."""

from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "EPI Access Control"
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    api_v1_prefix: str = "/api/v1"
    # Origins allowed to call the API from a browser (the admin panel).
    cors_origins: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:4173"]
    )

    # --- Database ---
    postgres_host: str = Field(default="db")
    postgres_port: int = Field(default=5432)
    postgres_db: str = Field(default="epi_access")
    postgres_user: str = Field(default="epi")
    postgres_password: str = Field(default="changeme")
    db_echo: bool = Field(default=False)

    # --- MQTT broker ---
    mqtt_host: str = Field(default="mosquitto")
    mqtt_port: int = Field(default=1883)
    mqtt_username: str | None = Field(default=None)
    mqtt_password: str | None = Field(default=None)
    mqtt_client_id: str = Field(default="epi-backend")
    mqtt_qos: int = Field(default=1)

    # --- Access control policy ---
    # Maximum time to wait for a vision inference result before denying access.
    session_timeout_seconds: float = Field(default=8.0)
    # Detections below this confidence are ignored (treated as not detected).
    detection_confidence_threshold: float = Field(default=0.60)
    # Ignore repeated scans of the same badge within this window.
    badge_cooldown_seconds: float = Field(default=5.0)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """Async SQLAlchemy connection URL."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_database_url(self) -> str:
        """Synchronous URL, used by Alembic migrations."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — read once per process."""
    return Settings()


settings = get_settings()

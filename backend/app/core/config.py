from functools import lru_cache
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_STORAGE_DIR = BACKEND_DIR / "storage"
DEFAULT_DB_FILE = DEFAULT_STORAGE_DIR / "app.db"


class Settings(BaseSettings):
    app_name: str = "Smart Study Platform"
    api_prefix: str = "/api"
    secret_key: str = "change-me-in-env"
    access_token_expire_minutes: int = 60 * 24
    database_url: str = f"sqlite:///{DEFAULT_DB_FILE.as_posix()}"
    storage_dir: Path = DEFAULT_STORAGE_DIR
    ai_provider: str = "demo"  # demo|openai|ollama
    openai_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    max_upload_mb: int = 25
    demo_mode_label: str = "DEMO MODE (deterministic generation)"

    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8")

    @field_validator("storage_dir", mode="before")
    @classmethod
    def resolve_storage_dir(cls, value: str | Path) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        return path.resolve()

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_sqlite_url(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        prefix = "sqlite:///"
        if not value.startswith(prefix):
            return value
        raw_path = value[len(prefix):]
        if raw_path.startswith("/"):
            return value
        resolved = (BACKEND_DIR / raw_path).resolve()
        return f"{prefix}{resolved.as_posix()}"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return settings

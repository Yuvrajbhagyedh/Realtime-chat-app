from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _async_database_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = "postgresql+asyncpg://" + url[len("postgresql://") :]
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./chat.db"
    redis_url: str = "memory://"
    secret_key: str = "dev-secret-change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7
    upload_dir: str = "uploads"
    cors_origins: str = "http://localhost:5173,http://localhost:8080,http://localhost:8000,http://127.0.0.1:8000"
    max_upload_bytes: int = 10 * 1024 * 1024
    frontend_dist: str = ""

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        return _async_database_url(value)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def use_memory_broker(self) -> bool:
        return self.redis_url.startswith("memory")


settings = Settings()

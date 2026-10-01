from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+asyncpg://receipts:receipts@localhost:5432/receipts"
    jwt_secret: str = "change-me"
    jwt_expires_minutes: int = 10080
    aws_region: str = "us-east-1"
    s3_bucket: str = "receipt-tracker-dev-uploads"
    textract_mode: Literal["mock", "aws"] = "mock"
    storage_mode: Literal["local", "s3"] = "local"
    local_upload_dir: str = "./.uploads"
    cors_origins: list[str] = ["http://localhost:3000"]
    max_upload_mb: int = 10
    low_confidence_threshold: float = 80
    sqs_queue_url: str = ""
    # Set true in production so the auth cookie is only sent over HTTPS.
    cookie_secure: bool = False
    # Artificial delay for the mock extractor, so the "processing" state is visible locally.
    mock_textract_delay_seconds: float = 1.5

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()

import json
import os
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import quote

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+asyncpg://receipts:receipts@localhost:5432/receipts"
    jwt_secret: str = "change-me"
    jwt_expires_minutes: int = 10080
    aws_region: str = "us-east-1"
    # Named profile from ~/.aws for local runs against real AWS. Values in .env don't reach
    # boto3 on their own (they're read into Settings, not the process environment), so this
    # one is exported for it.
    aws_profile: str = ""
    s3_bucket: str = "stub-dev-uploads"
    textract_mode: Literal["mock", "aws"] = "mock"
    storage_mode: Literal["local", "s3"] = "local"
    local_upload_dir: str = "./.uploads"
    # Comma-separated in the environment; NoDecode stops pydantic-settings parsing it as JSON.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    max_upload_mb: int = 10
    low_confidence_threshold: float = 80
    # Set to switch extraction to the SQS worker (Phase 4). Requires STORAGE_MODE=s3, since
    # uploads reach the queue through S3 ObjectCreated events.
    sqs_queue_url: str = ""
    # The RDS-managed secret as JSON ({"username", "password", "host", "port", "dbname"}).
    # When set (App Runner / ECS inject it), it overrides DATABASE_URL.
    database_secret: str = ""
    # Budget alert emails: "log" writes them to the log (dev), "ses" sends via Amazon SES.
    email_mode: Literal["log", "ses"] = "log"
    email_from: str = "Stub <alerts@example.com>"
    # Public URL of the web app, for links in emails.
    app_base_url: str = "http://localhost:3000"
    log_format: Literal["text", "json"] = "text"
    log_level: str = "INFO"
    rate_limit_enabled: bool = True
    # How many proxies in front of the API append to X-Forwarded-For (e.g. Vercel + App
    # Runner = 2). 0 trusts no header and uses the socket peer address.
    trusted_proxy_hops: int = 0
    # Set true in production so the auth cookie is only sent over HTTPS.
    cookie_secure: bool = False
    # Artificial delay for the mock extractor, so the "processing" state is visible locally.
    mock_textract_delay_seconds: float = 1.5
    # What the mock extractor returns for files that aren't demo receipts: "empty" (nothing
    # read; the user fills it in) or "sample" (made-up sample data; used by tests).
    mock_unknown_files: Literal["empty", "sample"] = "empty"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @model_validator(mode="after")
    def _derived(self) -> "Settings":
        if self.aws_profile:
            os.environ.setdefault("AWS_PROFILE", self.aws_profile)
        if self.database_secret:
            secret = json.loads(self.database_secret)
            self.database_url = (
                f"postgresql+asyncpg://{quote(secret['username'], safe='')}:"
                f"{quote(secret['password'], safe='')}@{secret['host']}:{secret.get('port', 5432)}"
                f"/{secret.get('dbname', 'receipts')}"
            )
        if self.sqs_queue_url and self.storage_mode != "s3":
            raise ValueError(
                "SQS_QUEUE_URL requires STORAGE_MODE=s3 (uploads arrive via S3 events)"
            )
        return self

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, v: object) -> object:
        """Accept "a,b" (as in .env.example) or a JSON array."""
        if isinstance(v, str):
            if v.strip().startswith("["):
                return json.loads(v)
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()

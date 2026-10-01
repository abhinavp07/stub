import pytest

from app.config import Settings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://localhost:3000", ["http://localhost:3000"]),
        ("http://a.test, https://b.test", ["http://a.test", "https://b.test"]),
        ('["http://json.test"]', ["http://json.test"]),
    ],
)
def test_cors_origins_from_env(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: list[str]
) -> None:
    monkeypatch.setenv("CORS_ORIGINS", raw)
    assert Settings(_env_file=None).cors_origins == expected  # type: ignore[call-arg]


def test_env_example_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every value in .env.example must parse, so `cp .env.example .env` just works."""
    from pathlib import Path

    env_example = Path(__file__).parents[2] / ".env.example"
    for name in ("CORS_ORIGINS", "TEXTRACT_MODE", "STORAGE_MODE", "MAX_UPLOAD_MB"):
        monkeypatch.delenv(name, raising=False)
    settings = Settings(_env_file=env_example)  # type: ignore[call-arg]
    assert settings.cors_origins == ["http://localhost:3000"]
    assert settings.textract_mode == "mock"
    assert settings.max_upload_bytes == 10 * 1024 * 1024


def test_database_secret_builds_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    secret = {
        "username": "app",
        "password": "p@ss/w:rd",
        "host": "db.internal",
        "port": 5433,
        "dbname": "receipts",
    }
    monkeypatch.setenv("DATABASE_SECRET", json.dumps(secret))
    url = Settings(_env_file=None).database_url  # type: ignore[call-arg]
    assert url == "postgresql+asyncpg://app:p%40ss%2Fw%3Ard@db.internal:5433/receipts"


def test_queue_mode_requires_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError

    monkeypatch.setenv("SQS_QUEUE_URL", "https://sqs.example/queue")
    monkeypatch.setenv("STORAGE_MODE", "local")
    with pytest.raises(ValidationError, match="requires STORAGE_MODE=s3"):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_aws_profile_from_env_file_reaches_boto3(
    monkeypatch: pytest.MonkeyPatch, tmp_path: "pytest.TempPathFactory"
) -> None:
    import os

    monkeypatch.delenv("AWS_PROFILE", raising=False)
    env_file = tmp_path / ".env"  # type: ignore[operator]
    env_file.write_text("AWS_PROFILE=stub\n")
    try:
        Settings(_env_file=env_file)  # type: ignore[call-arg]
        assert os.environ["AWS_PROFILE"] == "stub"
    finally:
        # Set by the code under test, not monkeypatch, so remove it by hand: a leftover
        # profile would break every boto3 client (and moto) in later tests.
        os.environ.pop("AWS_PROFILE", None)

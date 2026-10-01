import re
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_email(v: str) -> str:
    v = v.strip().lower()
    if not _EMAIL_RE.match(v):
        raise ValueError("Enter a valid email address")
    return v


class SignupRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=100)

    _email = field_validator("email")(_normalize_email)


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=128)

    @field_validator("email")
    @classmethod
    def lower(cls, v: str) -> str:
        return v.strip().lower()


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None
    currency: str

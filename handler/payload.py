"""Pydantic v2 models for request/response payloads."""

from typing import Any

from pydantic import BaseModel, field_validator


def _coerce_oid(value: Any) -> str:
    """Extract string from MongoDB $oid dict, coerce None to empty string."""
    if value is None:
        return ""
    if isinstance(value, dict) and "$oid" in value:
        return str(value["$oid"])
    return str(value)


class ChatRequest(BaseModel):
    companyId: str
    userId: str
    message: str
    userEmail: str = ""

    @field_validator("companyId", "userId", mode="before")
    @classmethod
    def coerce_oid(cls, value: Any) -> str:
        return _coerce_oid(value)

    @field_validator("userEmail", mode="before")
    @classmethod
    def strip_email(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be empty or whitespace-only")
        return value


class WebhookResponse(BaseModel):
    companyId: str
    userId: str
    message: str

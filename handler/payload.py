"""Pydantic v2 models for request/response payloads."""

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


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

    @field_validator("companyId", "userId", mode="before")
    @classmethod
    def coerce_oid(cls, value: Any) -> str:
        return _coerce_oid(value)

    @field_validator("message")
    @classmethod
    def message_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be empty or whitespace-only")
        return value


class FeedbackRequest(BaseModel):
    companyId: str
    userId: str
    score: int = Field(ge=1, le=5)
    text: Optional[str] = None
    sessionId: Optional[str] = None

    @field_validator("companyId", "userId", mode="before")
    @classmethod
    def coerce_oid(cls, value: Any) -> str:
        return _coerce_oid(value)


class ChatData(BaseModel):
    message: str


class ChatResponse(BaseModel):
    data: ChatData


class FeedbackData(BaseModel):
    status: str


class FeedbackResponse(BaseModel):
    data: FeedbackData


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail

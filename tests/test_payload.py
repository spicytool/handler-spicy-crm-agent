"""Tests for handler/payload.py - Pydantic v2 models."""

import pytest
from pydantic import ValidationError

from handler.payload import (
    ChatData,
    ChatRequest,
    ChatResponse,
    ErrorDetail,
    ErrorResponse,
    FeedbackData,
    FeedbackRequest,
    FeedbackResponse,
)


# ---------------------------------------------------------------------------
# ChatRequest tests
# ---------------------------------------------------------------------------

class TestChatRequest:
    def test_valid_request(self):
        req = ChatRequest(companyId="company1", userId="user1", message="Hello")
        assert req.companyId == "company1"
        assert req.userId == "user1"
        assert req.message == "Hello"

    def test_mongodb_oid_coercion_companyId(self):
        req = ChatRequest(
            companyId={"$oid": "abc123"},
            userId="user1",
            message="Hello",
        )
        assert req.companyId == "abc123"

    def test_mongodb_oid_coercion_userId(self):
        req = ChatRequest(
            companyId="company1",
            userId={"$oid": "def456"},
            message="Hello",
        )
        assert req.userId == "def456"

    def test_mongodb_oid_coercion_both(self):
        req = ChatRequest(
            companyId={"$oid": "abc123"},
            userId={"$oid": "def456"},
            message="Hi there",
        )
        assert req.companyId == "abc123"
        assert req.userId == "def456"

    def test_empty_message_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(companyId="c1", userId="u1", message="")

    def test_whitespace_only_message_rejected(self):
        with pytest.raises(ValidationError):
            ChatRequest(companyId="c1", userId="u1", message="   ")

    def test_none_companyId_coerced_to_empty_string(self):
        req = ChatRequest(companyId=None, userId="u1", message="Hello")
        assert req.companyId == ""

    def test_none_userId_coerced_to_empty_string(self):
        req = ChatRequest(companyId="c1", userId=None, message="Hello")
        assert req.userId == ""

    def test_message_with_leading_trailing_whitespace_is_valid(self):
        # Non-blank message with surrounding whitespace should be accepted
        req = ChatRequest(companyId="c1", userId="u1", message="  Hello  ")
        assert req.message == "  Hello  "


# ---------------------------------------------------------------------------
# FeedbackRequest tests
# ---------------------------------------------------------------------------

class TestFeedbackRequest:
    def test_valid_feedback(self):
        req = FeedbackRequest(companyId="c1", userId="u1", score=5)
        assert req.companyId == "c1"
        assert req.userId == "u1"
        assert req.score == 5

    def test_score_minimum_valid(self):
        req = FeedbackRequest(companyId="c1", userId="u1", score=1)
        assert req.score == 1

    def test_score_zero_rejected(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(companyId="c1", userId="u1", score=0)

    def test_score_six_rejected(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(companyId="c1", userId="u1", score=6)

    def test_score_negative_rejected(self):
        with pytest.raises(ValidationError):
            FeedbackRequest(companyId="c1", userId="u1", score=-1)

    def test_optional_text_field_defaults_none(self):
        req = FeedbackRequest(companyId="c1", userId="u1", score=3)
        assert req.text is None

    def test_optional_text_field_set(self):
        req = FeedbackRequest(companyId="c1", userId="u1", score=3, text="Great!")
        assert req.text == "Great!"

    def test_optional_sessionId_defaults_none(self):
        req = FeedbackRequest(companyId="c1", userId="u1", score=3)
        assert req.sessionId is None

    def test_optional_sessionId_set(self):
        req = FeedbackRequest(companyId="c1", userId="u1", score=3, sessionId="sess-99")
        assert req.sessionId == "sess-99"

    def test_mongodb_oid_coercion_companyId(self):
        req = FeedbackRequest(
            companyId={"$oid": "abc123"},
            userId="u1",
            score=4,
        )
        assert req.companyId == "abc123"

    def test_mongodb_oid_coercion_userId(self):
        req = FeedbackRequest(
            companyId="c1",
            userId={"$oid": "xyz789"},
            score=2,
        )
        assert req.userId == "xyz789"

    def test_mongodb_oid_coercion_both(self):
        req = FeedbackRequest(
            companyId={"$oid": "abc123"},
            userId={"$oid": "def456"},
            score=5,
        )
        assert req.companyId == "abc123"
        assert req.userId == "def456"


# ---------------------------------------------------------------------------
# Response envelope tests
# ---------------------------------------------------------------------------

class TestChatData:
    def test_has_message_field(self):
        data = ChatData(message="Hello back")
        assert data.message == "Hello back"

    def test_model_dump(self):
        data = ChatData(message="Hi")
        assert data.model_dump() == {"message": "Hi"}


class TestChatResponse:
    def test_wraps_chat_data(self):
        resp = ChatResponse(data=ChatData(message="reply"))
        assert resp.data.message == "reply"

    def test_model_dump_structure(self):
        resp = ChatResponse(data=ChatData(message="reply"))
        dumped = resp.model_dump()
        assert dumped == {"data": {"message": "reply"}}


class TestFeedbackData:
    def test_has_status_field(self):
        data = FeedbackData(status="ok")
        assert data.status == "ok"

    def test_model_dump(self):
        data = FeedbackData(status="accepted")
        assert data.model_dump() == {"status": "accepted"}


class TestFeedbackResponse:
    def test_wraps_feedback_data(self):
        resp = FeedbackResponse(data=FeedbackData(status="ok"))
        assert resp.data.status == "ok"

    def test_model_dump_structure(self):
        resp = FeedbackResponse(data=FeedbackData(status="ok"))
        dumped = resp.model_dump()
        assert dumped == {"data": {"status": "ok"}}


class TestErrorDetail:
    def test_has_code_and_message_fields(self):
        err = ErrorDetail(code="NOT_FOUND", message="Resource not found")
        assert err.code == "NOT_FOUND"
        assert err.message == "Resource not found"

    def test_model_dump(self):
        err = ErrorDetail(code="BAD_REQUEST", message="Invalid input")
        assert err.model_dump() == {"code": "BAD_REQUEST", "message": "Invalid input"}


class TestErrorResponse:
    def test_wraps_error_detail(self):
        resp = ErrorResponse(error=ErrorDetail(code="ERR", message="Something went wrong"))
        assert resp.error.code == "ERR"
        assert resp.error.message == "Something went wrong"

    def test_model_dump_structure(self):
        resp = ErrorResponse(error=ErrorDetail(code="ERR", message="oops"))
        dumped = resp.model_dump()
        assert dumped == {"error": {"code": "ERR", "message": "oops"}}

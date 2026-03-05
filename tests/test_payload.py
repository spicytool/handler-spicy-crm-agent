"""Tests for handler/payload.py - Pydantic v2 models."""

import pytest
from pydantic import ValidationError

from handler.payload import (
    ChatData,
    ChatRequest,
    ChatResponse,
    ErrorDetail,
    ErrorResponse,
    WebhookResponse,
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
        req = ChatRequest(companyId="c1", userId="u1", message="  Hello  ")
        assert req.message == "  Hello  "

    def test_userEmail_defaults_to_empty_string(self):
        req = ChatRequest(companyId="c1", userId="u1", message="Hello")
        assert req.userEmail == ""

    def test_userEmail_accepted_when_provided(self):
        req = ChatRequest(
            companyId="c1", userId="u1", message="Hello",
            userEmail="test@example.com",
        )
        assert req.userEmail == "test@example.com"

    def test_userEmail_strips_whitespace(self):
        req = ChatRequest(
            companyId="c1", userId="u1", message="Hello",
            userEmail="  test@example.com  ",
        )
        assert req.userEmail == "test@example.com"

    def test_userEmail_none_coerced_to_empty_string(self):
        req = ChatRequest(
            companyId="c1", userId="u1", message="Hello",
            userEmail=None,
        )
        assert req.userEmail == ""


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


# ---------------------------------------------------------------------------
# WebhookResponse tests
# ---------------------------------------------------------------------------

class TestWebhookResponse:
    def test_valid_response(self):
        resp = WebhookResponse(companyId="c1", userId="u1", message="reply")
        assert resp.companyId == "c1"
        assert resp.userId == "u1"
        assert resp.message == "reply"

    def test_model_dump_structure(self):
        resp = WebhookResponse(companyId="c1", userId="u1", message="reply")
        assert resp.model_dump() == {
            "companyId": "c1",
            "userId": "u1",
            "message": "reply",
        }


# ---------------------------------------------------------------------------
# Error model tests
# ---------------------------------------------------------------------------

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

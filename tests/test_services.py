"""Tests for handler/services.py - TDD (RED → GREEN → REFACTOR)."""

import os
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_part(text=None, function_call=None, function_response=None):
    part = MagicMock()
    part.text = text
    part.function_call = function_call
    part.function_response = function_response
    return part


def _make_event_obj(text=None, function_call=None, function_response=None):
    part = _make_part(text=text, function_call=function_call, function_response=function_response)
    content = MagicMock()
    content.parts = [part]
    event = MagicMock()
    event.content = content
    return event


async def _async_gen(*items):
    """Yield items from an async generator."""
    for item in items:
        yield item


# ---------------------------------------------------------------------------
# Import services (with Client patched at module level)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_client_at_import(monkeypatch):
    """Patch vertexai.Client before importing services."""
    monkeypatch.setenv("AGENT_ENGINE_ID", "test-engine-id")


# ---------------------------------------------------------------------------
# extract_text_from_event
# ---------------------------------------------------------------------------

class TestExtractTextFromEvent:
    def _import(self):
        # Import fresh each time to avoid stale state
        from handler import services
        return services.extract_text_from_event

    def test_object_event_with_text_returns_text(self):
        from handler.services import extract_text_from_event
        event = _make_event_obj(text="Hello")
        assert extract_text_from_event(event) == "Hello"

    def test_dict_event_with_text_returns_text(self):
        from handler.services import extract_text_from_event
        event = {"content": {"parts": [{"text": "World"}]}}
        assert extract_text_from_event(event) == "World"

    def test_object_function_call_event_returns_none(self):
        from handler.services import extract_text_from_event
        event = _make_event_obj(function_call={"name": "fn"})
        assert extract_text_from_event(event) is None

    def test_dict_function_call_event_returns_none(self):
        from handler.services import extract_text_from_event
        event = {"content": {"parts": [{"function_call": {"name": "fn"}}]}}
        assert extract_text_from_event(event) is None

    def test_dict_function_response_event_returns_none(self):
        from handler.services import extract_text_from_event
        event = {"content": {"parts": [{"function_response": {"name": "fn"}}]}}
        assert extract_text_from_event(event) is None

    def test_none_event_returns_none(self):
        from handler.services import extract_text_from_event
        assert extract_text_from_event(None) is None

    def test_empty_content_event_returns_none(self):
        from handler.services import extract_text_from_event
        event = MagicMock()
        event.content = None
        assert extract_text_from_event(event) is None

    def test_object_event_empty_parts_returns_none(self):
        from handler.services import extract_text_from_event
        content = MagicMock()
        content.parts = []
        event = MagicMock()
        event.content = content
        assert extract_text_from_event(event) is None

    def test_dict_event_no_text_key_returns_none(self):
        from handler.services import extract_text_from_event
        event = {"content": {"parts": [{}]}}
        assert extract_text_from_event(event) is None


# ---------------------------------------------------------------------------
# _find_or_create_session
# ---------------------------------------------------------------------------

class TestFindOrCreateSession:
    @pytest.mark.asyncio
    async def test_selects_most_recent_cloudrun_session(self):
        """Sessions exist with cloudrun label → selects most recent cloudrun one."""
        from handler import services

        session_cloudrun = MagicMock()
        session_cloudrun.name = "projects/p/locations/l/reasoningEngines/e/sessions/sess-cloudrun"
        session_cloudrun.update_time = "2024-06-01T00:00:00+00:00"
        session_cloudrun.labels = {"source": "cloudrun"}
        session_cloudrun.response = None  # prevent infinite recursion with MagicMock

        session_other = MagicMock()
        session_other.name = "projects/p/locations/l/reasoningEngines/e/sessions/sess-other"
        session_other.update_time = "2024-05-01T00:00:00+00:00"
        session_other.labels = {}
        session_other.response = None

        mock_client = MagicMock()
        mock_client.agent_engines.get.return_value = MagicMock()
        mock_client.agent_engines.sessions.list.return_value = [session_other, session_cloudrun]

        with patch.object(services, "client", mock_client):
            engine, session_id = await services._find_or_create_session(
                "user1", trace_id="t1"
            )

        assert session_id == "sess-cloudrun"

    @pytest.mark.asyncio
    async def test_selects_most_recent_when_no_cloudrun_label(self):
        """Sessions exist but none with cloudrun label → picks most recent by update_time."""
        from handler import services

        session_a = MagicMock()
        session_a.name = "projects/p/locations/l/reasoningEngines/e/sessions/sess-a"
        session_a.update_time = "2024-04-01T00:00:00+00:00"
        session_a.labels = {}
        session_a.response = None

        session_b = MagicMock()
        session_b.name = "projects/p/locations/l/reasoningEngines/e/sessions/sess-b"
        session_b.update_time = "2024-06-01T00:00:00+00:00"
        session_b.labels = {}
        session_b.response = None

        mock_client = MagicMock()
        mock_client.agent_engines.get.return_value = MagicMock()
        mock_client.agent_engines.sessions.list.return_value = [session_a, session_b]

        with patch.object(services, "client", mock_client):
            engine, session_id = await services._find_or_create_session(
                "user1", trace_id="t1"
            )

        assert session_id == "sess-b"

    @pytest.mark.asyncio
    async def test_creates_session_when_none_found(self):
        """No sessions → calls create and returns new session_id."""
        from handler import services

        created = MagicMock()
        created.name = "projects/p/locations/l/reasoningEngines/e/sessions/new-sess"
        created.response = None

        mock_client = MagicMock()
        mock_client.agent_engines.get.return_value = MagicMock()
        mock_client.agent_engines.sessions.list.return_value = []
        mock_client.agent_engines.sessions.create.return_value = created

        with patch.object(services, "client", mock_client):
            engine, session_id = await services._find_or_create_session(
                "user1", trace_id="t1"
            )

        mock_client.agent_engines.sessions.create.assert_called_once()
        assert session_id == "new-sess"

    @pytest.mark.asyncio
    async def test_creates_session_when_list_errors(self):
        """Session list error → falls through to create."""
        from handler import services

        created = MagicMock()
        created.name = "projects/p/locations/l/reasoningEngines/e/sessions/fallback-sess"
        created.response = None

        mock_client = MagicMock()
        mock_client.agent_engines.get.return_value = MagicMock()
        mock_client.agent_engines.sessions.list.side_effect = Exception("list failed")
        mock_client.agent_engines.sessions.create.return_value = created

        with patch.object(services, "client", mock_client):
            engine, session_id = await services._find_or_create_session(
                "user1", trace_id="t1"
            )

        mock_client.agent_engines.sessions.create.assert_called_once()
        assert session_id == "fallback-sess"


# ---------------------------------------------------------------------------
# call_agent_streaming
# ---------------------------------------------------------------------------

class TestCallAgentStreaming:
    @pytest.mark.asyncio
    async def test_yields_text_chunks(self):
        """Yields text chunks from agent text events."""
        from handler import services

        event_hello = _make_event_obj(text="Hello")
        event_world = _make_event_obj(text=" World")

        mock_engine = MagicMock()

        async def fake_stream(**kwargs):
            yield event_hello
            yield event_world

        mock_engine.async_stream_query = fake_stream

        with patch.object(services, "_find_or_create_session", AsyncMock(return_value=(mock_engine, "sess-1"))):
            chunks = []
            async for chunk in services.call_agent_streaming("user1", "hi", trace_id="t1"):
                chunks.append(chunk)

        assert chunks == ["Hello", " World"]

    @pytest.mark.asyncio
    async def test_skips_function_call_events(self):
        """Function call events are not yielded."""
        from handler import services

        event_text = _make_event_obj(text="Real text")
        event_fn = _make_event_obj(function_call={"name": "some_fn"})

        mock_engine = MagicMock()

        async def fake_stream(**kwargs):
            yield event_fn
            yield event_text

        mock_engine.async_stream_query = fake_stream

        with patch.object(services, "_find_or_create_session", AsyncMock(return_value=(mock_engine, "sess-1"))):
            chunks = []
            async for chunk in services.call_agent_streaming("user1", "hi", trace_id="t1"):
                chunks.append(chunk)

        assert chunks == ["Real text"]

    @pytest.mark.asyncio
    async def test_yields_fallback_when_all_function_call_events(self):
        """All function_call events → yields fallback Spanish message."""
        from handler import services

        event_fn = _make_event_obj(function_call={"name": "some_fn"})

        mock_engine = MagicMock()

        async def fake_stream(**kwargs):
            yield event_fn

        mock_engine.async_stream_query = fake_stream

        with patch.object(services, "_find_or_create_session", AsyncMock(return_value=(mock_engine, "sess-1"))):
            chunks = []
            async for chunk in services.call_agent_streaming("user1", "hi", trace_id="t1"):
                chunks.append(chunk)

        full_text = "".join(chunks)
        # Should have some fallback content
        assert len(full_text) > 0

    @pytest.mark.asyncio
    async def test_dict_text_events_yielded(self):
        """Dict-style text events are also yielded."""
        from handler import services

        event_dict = {"content": {"parts": [{"text": "DictText"}]}}

        mock_engine = MagicMock()

        async def fake_stream(**kwargs):
            yield event_dict

        mock_engine.async_stream_query = fake_stream

        with patch.object(services, "_find_or_create_session", AsyncMock(return_value=(mock_engine, "sess-1"))):
            chunks = []
            async for chunk in services.call_agent_streaming("user1", "hi", trace_id="t1"):
                chunks.append(chunk)

        assert chunks == ["DictText"]


# ---------------------------------------------------------------------------
# call_agent_sync
# ---------------------------------------------------------------------------

class TestCallAgentSync:
    @pytest.mark.asyncio
    async def test_aggregates_chunks_into_single_string(self):
        """Aggregates streaming chunks into a single string."""
        from handler import services

        async def fake_stream(user_id, message, *, trace_id=None):
            yield "Hello"
            yield " World"

        with patch.object(services, "call_agent_streaming", fake_stream):
            result = await services.call_agent_sync("user1", "hi", trace_id="t1")

        assert result == "Hello World"

    @pytest.mark.asyncio
    async def test_returns_fallback_on_error(self):
        """Returns fallback message when streaming fails."""
        from handler import services

        async def failing_stream(user_id, message, *, trace_id=None):
            raise RuntimeError("connection error")
            yield  # make it a generator

        with patch.object(services, "call_agent_streaming", failing_stream):
            result = await services.call_agent_sync("user1", "hi", trace_id="t1")

        # Should return some fallback text, not raise
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# submit_feedback
# ---------------------------------------------------------------------------

class TestSubmitFeedback:
    @pytest.mark.asyncio
    async def test_returns_success_indicator(self):
        """submit_feedback returns a success indicator dict or truthy value."""
        from handler import services

        result = await services.submit_feedback(
            user_id="user1",
            score=5,
            text="Great!",
            session_id="sess-1",
            trace_id="t1",
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_accepts_minimal_params(self):
        """submit_feedback works with just user_id and score."""
        from handler import services

        result = await services.submit_feedback(user_id="user1", score=3)
        assert result is not None


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

class TestEnvFlag:
    def test_returns_true_for_1(self, monkeypatch):
        from handler.services import _env_flag
        monkeypatch.setenv("TEST_FLAG", "1")
        assert _env_flag("TEST_FLAG") is True

    def test_returns_true_for_true(self, monkeypatch):
        from handler.services import _env_flag
        monkeypatch.setenv("TEST_FLAG", "true")
        assert _env_flag("TEST_FLAG") is True

    def test_returns_true_for_yes(self, monkeypatch):
        from handler.services import _env_flag
        monkeypatch.setenv("TEST_FLAG", "yes")
        assert _env_flag("TEST_FLAG") is True

    def test_returns_false_for_0(self, monkeypatch):
        from handler.services import _env_flag
        monkeypatch.setenv("TEST_FLAG", "0")
        assert _env_flag("TEST_FLAG") is False

    def test_returns_false_for_missing(self, monkeypatch):
        from handler.services import _env_flag
        monkeypatch.delenv("TEST_FLAG", raising=False)
        assert _env_flag("TEST_FLAG") is False


class TestSafeSnippet:
    def test_truncates_long_strings(self):
        from handler.services import _safe_snippet
        long = "x" * 200
        result = _safe_snippet(long, limit=120)
        assert len(result) == 120

    def test_short_string_unchanged(self):
        from handler.services import _safe_snippet
        result = _safe_snippet("hello", limit=120)
        assert result == "hello"

    def test_none_returns_empty_string(self):
        from handler.services import _safe_snippet
        assert _safe_snippet(None) == ""

    def test_replaces_newlines(self):
        from handler.services import _safe_snippet
        result = _safe_snippet("line1\nline2")
        assert "\\n" in result
        assert "\n" not in result


class TestLogKv:
    def test_produces_structured_log_output(self, caplog):
        from handler.services import log_kv
        with caplog.at_level(logging.INFO, logger="handler.services"):
            log_kv("test_event", "trace-123", key1="val1", key2=42)

        assert len(caplog.records) == 1
        msg = caplog.records[0].message
        assert "test_event" in msg
        assert "trace-123" in msg

    def test_skips_none_values(self, caplog):
        from handler.services import log_kv
        with caplog.at_level(logging.INFO, logger="handler.services"):
            log_kv("test_event", "trace-123", present="yes", absent=None)

        msg = caplog.records[0].message
        assert "present" in msg
        assert "absent" not in msg


# ---------------------------------------------------------------------------
# _get_field helper
# ---------------------------------------------------------------------------

class TestGetField:
    def test_dict_access(self):
        from handler.services import _get_field
        assert _get_field({"key": "val"}, "key") == "val"

    def test_object_access(self):
        from handler.services import _get_field
        obj = MagicMock()
        obj.key = "objval"
        assert _get_field(obj, "key") == "objval"

    def test_missing_key_returns_default(self):
        from handler.services import _get_field
        assert _get_field({}, "missing", "default") == "default"

    def test_none_obj_returns_default(self):
        from handler.services import _get_field
        assert _get_field(None, "key") is None


# ---------------------------------------------------------------------------
# _extract_session_id helper
# ---------------------------------------------------------------------------

class TestExtractSessionId:
    def test_extracts_from_full_name(self):
        from handler.services import _extract_session_id
        # Use a simple namespace object to avoid MagicMock recursion
        session = {"name": "projects/p/locations/l/reasoningEngines/e/sessions/my-session-id"}
        result = _extract_session_id(session)
        assert result == "my-session-id"

    def test_returns_none_for_none(self):
        from handler.services import _extract_session_id
        assert _extract_session_id(None) is None

    def test_handles_sessions_prefix(self):
        from handler.services import _extract_session_id
        session = {"name": "sessions/short-id"}
        result = _extract_session_id(session)
        assert result == "short-id"

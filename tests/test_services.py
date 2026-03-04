"""Tests for handler/services.py - TDD (RED → GREEN → REFACTOR)."""

import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
# extract_text_from_event (dict-only)
# ---------------------------------------------------------------------------

class TestExtractTextFromEvent:
    def test_dict_event_with_text_returns_text(self):
        from handler.services import extract_text_from_event
        event = {"content": {"parts": [{"text": "World"}]}}
        assert extract_text_from_event(event) == "World"

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

    def test_non_dict_event_returns_none(self):
        from handler.services import extract_text_from_event
        assert extract_text_from_event("not a dict") is None

    def test_dict_event_no_content_returns_none(self):
        from handler.services import extract_text_from_event
        assert extract_text_from_event({}) is None

    def test_dict_event_content_not_dict_returns_none(self):
        from handler.services import extract_text_from_event
        assert extract_text_from_event({"content": "string"}) is None

    def test_dict_event_empty_parts_returns_none(self):
        from handler.services import extract_text_from_event
        assert extract_text_from_event({"content": {"parts": []}}) is None

    def test_dict_event_no_text_key_returns_none(self):
        from handler.services import extract_text_from_event
        event = {"content": {"parts": [{}]}}
        assert extract_text_from_event(event) is None

    def test_dict_event_empty_text_returns_none(self):
        from handler.services import extract_text_from_event
        event = {"content": {"parts": [{"text": ""}]}}
        assert extract_text_from_event(event) is None

    def test_non_dict_part_is_skipped(self):
        from handler.services import extract_text_from_event
        event = {"content": {"parts": ["not a dict", {"text": "found"}]}}
        assert extract_text_from_event(event) == "found"


# ---------------------------------------------------------------------------
# extract_session_id
# ---------------------------------------------------------------------------

class TestExtractSessionId:
    def test_extracts_from_full_name_dict(self):
        from handler.services import extract_session_id
        session = {"name": "projects/p/locations/l/reasoningEngines/e/sessions/my-session-id"}
        assert extract_session_id(session) == "my-session-id"

    def test_extracts_from_sessions_prefix_dict(self):
        from handler.services import extract_session_id
        session = {"name": "sessions/short-id"}
        assert extract_session_id(session) == "short-id"

    def test_extracts_bare_name_dict(self):
        from handler.services import extract_session_id
        session = {"name": "bare-id"}
        assert extract_session_id(session) == "bare-id"

    def test_returns_none_for_none(self):
        from handler.services import extract_session_id
        assert extract_session_id(None) is None

    def test_extracts_from_object_name(self):
        from handler.services import extract_session_id

        class FakeSession:
            name = "projects/p/locations/l/reasoningEngines/e/sessions/obj-sess"
        assert extract_session_id(FakeSession()) == "obj-sess"

    def test_handles_operation_wrapper(self):
        from handler.services import extract_session_id

        class FakeResponse:
            name = "projects/p/locations/l/reasoningEngines/e/sessions/wrapped-id"

        class FakeOperation:
            response = FakeResponse()
        assert extract_session_id(FakeOperation()) == "wrapped-id"

    def test_returns_none_for_empty_name(self):
        from handler.services import extract_session_id
        session = {"name": ""}
        assert extract_session_id(session) is None


# ---------------------------------------------------------------------------
# _find_or_create_session
# ---------------------------------------------------------------------------

class TestFindOrCreateSession:
    @pytest.mark.asyncio
    async def test_selects_first_session(self):
        """Sessions exist → selects first one returned."""
        from handler import services

        mock_client = MagicMock()
        mock_client.agent_engines.get.return_value = MagicMock()
        mock_client.agent_engines.sessions.list.return_value = [
            {"name": "projects/p/locations/l/reasoningEngines/e/sessions/sess-first"},
            {"name": "projects/p/locations/l/reasoningEngines/e/sessions/sess-second"},
        ]

        with patch.object(services, "client", mock_client):
            engine, session_id = await services._find_or_create_session(
                "user1", trace_id="t1"
            )

        assert session_id == "sess-first"

    @pytest.mark.asyncio
    async def test_creates_session_when_none_found(self):
        """No sessions → calls create and returns new session_id."""
        from handler import services

        mock_client = MagicMock()
        mock_client.agent_engines.get.return_value = MagicMock()
        mock_client.agent_engines.sessions.list.return_value = []
        mock_client.agent_engines.sessions.create.return_value = {
            "name": "projects/p/locations/l/reasoningEngines/e/sessions/new-sess"
        }

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

        mock_client = MagicMock()
        mock_client.agent_engines.get.return_value = MagicMock()
        mock_client.agent_engines.sessions.list.side_effect = Exception("list failed")
        mock_client.agent_engines.sessions.create.return_value = {
            "name": "projects/p/locations/l/reasoningEngines/e/sessions/fallback-sess"
        }

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
        """Yields text chunks from agent dict events."""
        from handler import services

        event_hello = {"content": {"parts": [{"text": "Hello"}]}}
        event_world = {"content": {"parts": [{"text": " World"}]}}

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

        event_text = {"content": {"parts": [{"text": "Real text"}]}}
        event_fn = {"content": {"parts": [{"function_call": {"name": "some_fn"}}]}}

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
    async def test_yields_fallback_when_no_text_events(self):
        """No text events → yields fallback Spanish message."""
        from handler import services

        event_fn = {"content": {"parts": [{"function_call": {"name": "some_fn"}}]}}

        mock_engine = MagicMock()

        async def fake_stream(**kwargs):
            yield event_fn

        mock_engine.async_stream_query = fake_stream

        with patch.object(services, "_find_or_create_session", AsyncMock(return_value=(mock_engine, "sess-1"))):
            chunks = []
            async for chunk in services.call_agent_streaming("user1", "hi", trace_id="t1"):
                chunks.append(chunk)

        full_text = "".join(chunks)
        assert len(full_text) > 0


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

        assert isinstance(result, str)
        assert len(result) > 0

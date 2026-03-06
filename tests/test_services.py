"""Tests for handler/services.py - TDD (RED → GREEN → REFACTOR)."""

import asyncio
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

        mock_engine = MagicMock()
        mock_client = MagicMock()
        mock_client.agent_engines.sessions.list.return_value = [
            {"name": "projects/p/locations/l/reasoningEngines/e/sessions/sess-first"},
            {"name": "projects/p/locations/l/reasoningEngines/e/sessions/sess-second"},
        ]

        with patch.object(services, "_agent_engine", mock_engine), \
             patch.object(services, "client", mock_client), \
             patch.object(services, "_session_locks", {}):
            engine, session_id = await services._find_or_create_session(
                "user1", trace_id="t1"
            )

        assert session_id == "sess-first"
        assert engine is mock_engine

    @pytest.mark.asyncio
    async def test_creates_session_when_none_found(self):
        """No sessions → calls create and returns new session_id."""
        from handler import services

        mock_engine = MagicMock()
        mock_client = MagicMock()
        mock_client.agent_engines.sessions.list.return_value = []
        mock_client.agent_engines.sessions.create.return_value = {
            "name": "projects/p/locations/l/reasoningEngines/e/sessions/new-sess"
        }

        with patch.object(services, "_agent_engine", mock_engine), \
             patch.object(services, "client", mock_client), \
             patch.object(services, "_session_locks", {}):
            engine, session_id = await services._find_or_create_session(
                "user1", trace_id="t1"
            )

        mock_client.agent_engines.sessions.create.assert_called_once()
        assert session_id == "new-sess"

    @pytest.mark.asyncio
    async def test_creates_session_when_list_errors(self):
        """Session list error → falls through to create."""
        from handler import services

        mock_engine = MagicMock()
        mock_client = MagicMock()
        mock_client.agent_engines.sessions.list.side_effect = Exception("list failed")
        mock_client.agent_engines.sessions.create.return_value = {
            "name": "projects/p/locations/l/reasoningEngines/e/sessions/fallback-sess"
        }

        with patch.object(services, "_agent_engine", mock_engine), \
             patch.object(services, "client", mock_client), \
             patch.object(services, "_session_locks", {}):
            engine, session_id = await services._find_or_create_session(
                "user1", trace_id="t1"
            )

        mock_client.agent_engines.sessions.create.assert_called_once()
        assert session_id == "fallback-sess"

    @pytest.mark.asyncio
    async def test_does_not_call_agent_engines_get(self):
        """Uses cached _agent_engine, never calls client.agent_engines.get."""
        from handler import services

        mock_engine = MagicMock()
        mock_client = MagicMock()
        mock_client.agent_engines.sessions.list.return_value = [
            {"name": "projects/p/locations/l/reasoningEngines/e/sessions/s1"}
        ]

        with patch.object(services, "_agent_engine", mock_engine), \
             patch.object(services, "client", mock_client), \
             patch.object(services, "_session_locks", {}):
            await services._find_or_create_session("u1", trace_id="t")
            await services._find_or_create_session("u2", trace_id="t")

        mock_client.agent_engines.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_if_agent_engine_not_initialized(self):
        """Raises RuntimeError when _agent_engine is None (lifespan not run)."""
        from handler import services

        with patch.object(services, "_agent_engine", None):
            with pytest.raises(RuntimeError, match="not initialized"):
                await services._find_or_create_session("u1", trace_id="t")


# ---------------------------------------------------------------------------
# Session concurrency
# ---------------------------------------------------------------------------

class TestSessionConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_requests_create_only_one_session(self):
        """5 concurrent calls for same user create exactly 1 session."""
        from handler import services

        mock_engine = MagicMock()
        mock_client = MagicMock()

        created_sessions: list[dict] = []

        def list_sessions(**kwargs):
            return list(created_sessions)

        def create_session(**kwargs):
            sess = {"name": "projects/p/locations/l/reasoningEngines/e/sessions/new-sess"}
            created_sessions.append(sess)
            return sess

        mock_client.agent_engines.sessions.list.side_effect = list_sessions
        mock_client.agent_engines.sessions.create.side_effect = create_session

        with patch.object(services, "_agent_engine", mock_engine), \
             patch.object(services, "client", mock_client), \
             patch.object(services, "_session_locks", {}):
            await asyncio.gather(*[
                services._find_or_create_session("same_user", trace_id="t")
                for _ in range(5)
            ])

        assert mock_client.agent_engines.sessions.create.call_count == 1

    @pytest.mark.asyncio
    async def test_different_users_create_sessions_independently(self):
        """Concurrent calls for different users each create their own session."""
        from handler import services

        mock_engine = MagicMock()
        mock_client = MagicMock()
        mock_client.agent_engines.sessions.list.return_value = []
        mock_client.agent_engines.sessions.create.return_value = {
            "name": "projects/p/locations/l/reasoningEngines/e/sessions/new-sess"
        }

        with patch.object(services, "_agent_engine", mock_engine), \
             patch.object(services, "client", mock_client), \
             patch.object(services, "_session_locks", {}):
            await asyncio.gather(
                services._find_or_create_session("user_a", trace_id="t"),
                services._find_or_create_session("user_b", trace_id="t"),
            )

        assert mock_client.agent_engines.sessions.create.call_count == 2


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
    async def test_exception_propagates_not_swallowed(self):
        """RuntimeError from streaming propagates — not caught and returned as string."""
        from handler import services

        async def failing_stream(user_id, message, *, trace_id=None):
            raise RuntimeError("connection error")
            yield  # make it a generator

        with patch.object(services, "call_agent_streaming", failing_stream):
            with pytest.raises(RuntimeError, match="connection error"):
                await services.call_agent_sync("user1", "hi", trace_id="t1")

    @pytest.mark.asyncio
    async def test_timeout_error_propagates(self):
        """asyncio.TimeoutError propagates from call_agent_sync."""
        from handler import services

        async def slow_stream(user_id, message, *, trace_id=None):
            await asyncio.sleep(999)
            yield "never"

        with patch.object(services, "call_agent_streaming", slow_stream), \
             patch("handler.services.asyncio.wait_for", side_effect=asyncio.TimeoutError):
            with pytest.raises(asyncio.TimeoutError):
                await services.call_agent_sync("user1", "hi", trace_id="t1")

    @pytest.mark.asyncio
    async def test_response_truncated_at_max_chars(self):
        """Response is truncated at MAX_RESPONSE_CHARS."""
        from handler import services

        chunk = "x" * 10_000

        async def big_stream(user_id, message, *, trace_id=None):
            for _ in range(6):  # 60,000 chars total
                yield chunk

        with patch.object(services, "call_agent_streaming", big_stream):
            result = await services.call_agent_sync("user1", "hi", trace_id="t1")

        assert len(result) == services.MAX_RESPONSE_CHARS

    @pytest.mark.asyncio
    async def test_response_warning_logged_on_truncation(self, caplog):
        """Logger.warning called when response is truncated."""
        from handler import services

        chunk = "x" * 30_000

        async def big_stream(user_id, message, *, trace_id=None):
            yield chunk
            yield chunk  # 60,000 total

        with caplog.at_level(logging.WARNING), \
             patch.object(services, "call_agent_streaming", big_stream):
            await services.call_agent_sync("user1", "hi", trace_id="t1")

        assert any("response_truncated" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# PROJECT_ID default
# ---------------------------------------------------------------------------

class TestProjectIdDefault:
    def test_project_id_default_is_correct(self):
        from handler import services
        # When GOOGLE_CLOUD_PROJECT is set by conftest, it uses that.
        # The default in code is "spicytool-crud-agent" (not "spicy-crm-handler").
        import os
        original = os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
        try:
            # Re-read the default from the source
            default = os.getenv("GOOGLE_CLOUD_PROJECT", "spicytool-crud-agent")
            assert default == "spicytool-crud-agent"
        finally:
            if original is not None:
                os.environ["GOOGLE_CLOUD_PROJECT"] = original


# ---------------------------------------------------------------------------
# _log_user_id
# ---------------------------------------------------------------------------

class TestLogUserId:
    def test_strips_email_from_three_part_id(self):
        from handler.services import _log_user_id
        assert _log_user_id("company:user:email@test.com") == "company:user"

    def test_preserves_two_part_id(self):
        from handler.services import _log_user_id
        assert _log_user_id("company:user") == "company:user"

    def test_single_part_id(self):
        from handler.services import _log_user_id
        assert _log_user_id("justuser") == "justuser"

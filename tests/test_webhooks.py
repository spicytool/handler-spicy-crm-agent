"""Tests for handler/webhooks.py FastAPI endpoints."""

import json
import os

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _async_gen(*chunks):
    """Helper: async generator that yields the given chunks."""
    for chunk in chunks:
        yield chunk


async def _async_gen_raise(exc):
    """Helper: async generator that raises after starting."""
    if False:  # pragma: no cover
        yield  # make it an async generator
    raise exc


# ---------------------------------------------------------------------------
# App import (after env is set via autouse fixture in conftest)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module", autouse=True)
def ensure_env():
    """Set env vars before module-level import of services."""
    os.environ.setdefault("AGENT_ENGINE_ID", "test-engine-id")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")


@pytest.fixture
def app():
    """Import and return the FastAPI app, patching services at module import."""
    with patch("handler.services.Client"):
        from handler.webhooks import app as _app
        return _app


@pytest.fixture
async def client(app):
    """Async test client for the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ---------------------------------------------------------------------------
# Test: GET /health
# ---------------------------------------------------------------------------

async def test_health_returns_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Test: POST /api/chat SSE (streaming, default)
# ---------------------------------------------------------------------------

async def test_chat_sse_streams_chunks(client):
    """SSE stream yields text chunks and [DONE]."""
    with patch(
        "handler.webhooks.call_agent_streaming",
        return_value=_async_gen("Hello", " World"),
    ):
        async with client.stream("POST", "/api/chat", json={
            "companyId": "c1",
            "userId": "u1",
            "message": "Hi",
        }) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            body = await response.aread()
            text = body.decode()

    assert 'data: {"text": "Hello"}' in text
    assert 'data: {"text": " World"}' in text
    assert "data: [DONE]" in text


async def test_chat_sse_error_yields_error_event(client):
    """When call_agent_streaming raises, SSE yields error event."""
    with patch(
        "handler.webhooks.call_agent_streaming",
        return_value=_async_gen_raise(Exception("boom")),
    ):
        async with client.stream("POST", "/api/chat", json={
            "companyId": "c1",
            "userId": "u1",
            "message": "Hi",
        }) as response:
            body = await response.aread()
            text = body.decode()

    assert "event: error" in text
    assert "agent_error" in text
    assert "Error al procesar tu solicitud" in text


# ---------------------------------------------------------------------------
# Test: POST /api/chat?stream=false (JSON sync mode)
# ---------------------------------------------------------------------------

async def test_chat_sync_returns_message(client):
    """sync mode returns JSON with data.message."""
    with patch(
        "handler.webhooks.call_agent_sync",
        new_callable=AsyncMock,
        return_value="Hello World",
    ):
        response = await client.post("/api/chat?stream=false", json={
            "companyId": "c1",
            "userId": "u1",
            "message": "Hi",
        })

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["message"] == "Hello World"


async def test_chat_sync_error_returns_500(client):
    """When call_agent_sync raises, returns 500 with error envelope."""
    with patch(
        "handler.webhooks.call_agent_sync",
        new_callable=AsyncMock,
        side_effect=Exception("boom"),
    ):
        response = await client.post("/api/chat?stream=false", json={
            "companyId": "c1",
            "userId": "u1",
            "message": "Hi",
        })

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "agent_error"
    assert body["error"]["message"] == "Error al procesar tu solicitud"


# ---------------------------------------------------------------------------
# Test: POST /api/chat validation
# ---------------------------------------------------------------------------

async def test_chat_empty_message_returns_422(client):
    """Empty message fails Pydantic validation → 422."""
    response = await client.post("/api/chat", json={
        "companyId": "c1",
        "userId": "u1",
        "message": "",
    })
    assert response.status_code == 422


async def test_chat_whitespace_message_returns_422(client):
    """Whitespace-only message fails validation → 422."""
    response = await client.post("/api/chat", json={
        "companyId": "c1",
        "userId": "u1",
        "message": "   ",
    })
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Test: _event_generator directly
# ---------------------------------------------------------------------------

async def test_event_generator_yields_chunks_and_done():
    """Test _event_generator async generator directly."""
    with patch("handler.services.Client"):
        from handler.webhooks import _event_generator

    with patch(
        "handler.webhooks.call_agent_streaming",
        return_value=_async_gen("chunk1", "chunk2"),
    ):
        events = []
        async for event in _event_generator("u1", "hello", "trace123"):
            events.append(event)

    assert events[0] == {"data": json.dumps({"text": "chunk1"})}
    assert events[1] == {"data": json.dumps({"text": "chunk2"})}
    assert events[2] == {"data": "[DONE]"}


async def test_event_generator_yields_error_event_on_exception():
    """Test _event_generator emits error event when exception raised."""
    with patch("handler.services.Client"):
        from handler.webhooks import _event_generator

    with patch(
        "handler.webhooks.call_agent_streaming",
        return_value=_async_gen_raise(RuntimeError("fail")),
    ):
        events = []
        async for event in _event_generator("u1", "hello", "trace123"):
            events.append(event)

    assert len(events) == 1
    assert events[0]["event"] == "error"
    error_data = json.loads(events[0]["data"])
    assert error_data["code"] == "agent_error"
    assert error_data["message"] == "Error al procesar tu solicitud"


# ---------------------------------------------------------------------------
# Test: lifespan (startup/shutdown logging)
# ---------------------------------------------------------------------------

async def test_lifespan_logs_startup_and_shutdown():
    """Lifespan context manager logs startup and shutdown."""
    with patch("handler.services.Client"):
        from handler.webhooks import lifespan, app as _app

    with patch("handler.webhooks.logger") as mock_logger:
        async with lifespan(_app):
            startup_calls = [c for c in mock_logger.info.call_args_list if "startup" in str(c)]
            assert len(startup_calls) == 1

        shutdown_calls = [c for c in mock_logger.info.call_args_list if "shutdown" in str(c)]
        assert len(shutdown_calls) == 1

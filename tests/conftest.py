"""Shared pytest fixtures for handler-spicy-crm-agent tests."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Environment setup - must happen before module import
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def set_required_env(monkeypatch):
    """Ensure required environment variables are set before each test."""
    monkeypatch.setenv("AGENT_ENGINE_ID", "test-engine-id")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")


# ---------------------------------------------------------------------------
# Vertex AI client mocks
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_client():
    """Patch vertexai.Client so no real GCP calls are made."""
    with patch("handler.services.Client") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_agent_engine():
    """Fake agent engine object with async_stream_query method."""
    engine = MagicMock()
    engine.async_stream_query = AsyncMock()
    return engine


# ---------------------------------------------------------------------------
# Event fixtures
# ---------------------------------------------------------------------------

def _make_part(text=None, function_call=None, function_response=None):
    """Build a mock part object."""
    part = MagicMock()
    part.text = text
    part.function_call = function_call
    part.function_response = function_response
    return part


def _make_event_obj(text=None, function_call=None, function_response=None):
    """Build a mock object-style event."""
    part = _make_part(text=text, function_call=function_call, function_response=function_response)
    content = MagicMock()
    content.parts = [part]
    event = MagicMock()
    event.content = content
    return event


@pytest.fixture
def sample_text_event_obj():
    """Object-style event with .content.parts[0].text = 'Hello'."""
    return _make_event_obj(text="Hello")


@pytest.fixture
def sample_text_event_dict():
    """Dict-style event with text 'World'."""
    return {"content": {"parts": [{"text": "World"}]}}


@pytest.fixture
def sample_function_call_event():
    """Object-style event with function_call part (no text)."""
    return _make_event_obj(function_call={"name": "some_function", "args": {}})


@pytest.fixture
def sample_sessions():
    """List of mock session objects with name, update_time, labels."""
    sessions = []
    for i in range(3):
        s = MagicMock()
        s.name = f"projects/test-project/locations/us-central1/reasoningEngines/test-engine-id/sessions/session-{i}"
        s.update_time = f"2024-01-0{i+1}T00:00:00+00:00"
        s.labels = {"source": "cloudrun"} if i == 0 else {}
        sessions.append(s)
    return sessions

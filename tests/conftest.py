"""Shared pytest fixtures for handler-spicy-crm-agent tests."""

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
    monkeypatch.setenv("WEBHOOK_SECRET_LOCAL", "test-secret")


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
# Event fixtures (dict-only)
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_text_event_dict():
    """Dict-style event with text 'World'."""
    return {"content": {"parts": [{"text": "World"}]}}


@pytest.fixture
def sample_sessions():
    """List of dict session objects with name field."""
    return [
        {"name": f"projects/test-project/locations/us-central1/reasoningEngines/test-engine-id/sessions/session-{i}"}
        for i in range(3)
    ]

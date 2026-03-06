"""Tests for handler/webhooks.py FastAPI endpoints."""

import os

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch, MagicMock


# ---------------------------------------------------------------------------
# App import (after env is set via autouse fixture in conftest)
# ---------------------------------------------------------------------------

WEBHOOK_TEST_SECRET = "test-webhook-secret"


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
    with patch("handler.auth.WEBHOOK_SECRET", WEBHOOK_TEST_SECRET):
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


# ---------------------------------------------------------------------------
# Test: POST /webhook
# ---------------------------------------------------------------------------

async def test_webhook_success(client):
    """Happy path: returns response mirroring request shape with agent reply."""
    with patch(
        "handler.webhooks.call_agent_sync",
        new_callable=AsyncMock,
        return_value="Encontré 3 contactos con nombre Juan",
    ):
        response = await client.post(
            "/webhook",
            json={
                "companyId": "c1",
                "userId": "u1",
                "message": "Busca contactos con nombre Juan",
            },
            headers={"Authorization": f"Bearer {WEBHOOK_TEST_SECRET}"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "companyId": "c1",
        "userId": "u1",
        "message": "Encontré 3 contactos con nombre Juan",
    }


async def test_webhook_empty_message_422(client):
    """Empty message fails Pydantic validation → 422."""
    response = await client.post(
        "/webhook",
        json={
            "companyId": "c1",
            "userId": "u1",
            "message": "",
        },
        headers={"Authorization": f"Bearer {WEBHOOK_TEST_SECRET}"},
    )
    assert response.status_code == 422


async def test_webhook_user_id_format(client):
    """Verify call_agent_sync receives 'companyId:userId:userEmail' format."""
    mock_sync = AsyncMock(return_value="ok")
    with patch("handler.webhooks.call_agent_sync", mock_sync):
        await client.post(
            "/webhook",
            json={
                "companyId": "company123",
                "userId": "user456",
                "message": "hello",
            },
            headers={"Authorization": f"Bearer {WEBHOOK_TEST_SECRET}"},
        )

    mock_sync.assert_called_once()
    args = mock_sync.call_args
    assert args[0][0] == "company123:user456:"
    assert args[0][1] == "hello"


async def test_webhook_user_id_format_with_email(client):
    """Verify call_agent_sync receives userEmail in composite user_id."""
    mock_sync = AsyncMock(return_value="ok")
    with patch("handler.webhooks.call_agent_sync", mock_sync):
        await client.post(
            "/webhook",
            json={
                "companyId": "company123",
                "userId": "user456",
                "userEmail": "owner@example.com",
                "message": "hello",
            },
            headers={"Authorization": f"Bearer {WEBHOOK_TEST_SECRET}"},
        )

    mock_sync.assert_called_once()
    args = mock_sync.call_args
    assert args[0][0] == "company123:user456:owner@example.com"
    assert args[0][1] == "hello"

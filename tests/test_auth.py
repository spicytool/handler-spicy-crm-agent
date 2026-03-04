"""Tests for handler/auth.py bearer token authentication."""

import os

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch


TEST_SECRET = "test-webhook-secret-abc123"


@pytest.fixture(scope="module", autouse=True)
def ensure_env():
    """Set env vars before module-level import of services."""
    os.environ.setdefault("AGENT_ENGINE_ID", "test-engine-id")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "us-central1")


@pytest.fixture
def app(monkeypatch):
    """Import app with WEBHOOK_SECRET set."""
    monkeypatch.setattr("handler.auth.WEBHOOK_SECRET", TEST_SECRET)
    with patch("handler.services.Client"):
        from handler.webhooks import app as _app
        return _app


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


VALID_PAYLOAD = {
    "companyId": "c1",
    "userId": "u1",
    "message": "hello",
}


# ---------------------------------------------------------------------------
# Webhook auth tests
# ---------------------------------------------------------------------------

async def test_webhook_valid_token(client):
    """Valid bearer token returns 200."""
    with patch(
        "handler.webhooks.call_agent_sync",
        new_callable=AsyncMock,
        return_value="ok",
    ):
        response = await client.post(
            "/webhook",
            json=VALID_PAYLOAD,
            headers={"Authorization": f"Bearer {TEST_SECRET}"},
        )
    assert response.status_code == 200


async def test_webhook_missing_header(client):
    """No Authorization header returns 401."""
    response = await client.post("/webhook", json=VALID_PAYLOAD)
    assert response.status_code == 401


async def test_webhook_wrong_token(client):
    """Wrong token returns 401."""
    response = await client.post(
        "/webhook",
        json=VALID_PAYLOAD,
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


async def test_webhook_malformed_header(client):
    """Non-Bearer auth scheme returns 401."""
    response = await client.post(
        "/webhook",
        json=VALID_PAYLOAD,
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert response.status_code == 401


async def test_webhook_empty_bearer(client):
    """Bearer with no token returns 401."""
    response = await client.post(
        "/webhook",
        json=VALID_PAYLOAD,
        headers={"Authorization": "Bearer "},
    )
    assert response.status_code == 401


async def test_webhook_secret_not_configured():
    """If WEBHOOK_SECRET is empty, returns 500."""
    with patch("handler.auth.WEBHOOK_SECRET", ""):
        with patch("handler.services.Client"):
            from handler.webhooks import app as _app
        async with AsyncClient(
            transport=ASGITransport(app=_app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/webhook",
                json=VALID_PAYLOAD,
                headers={"Authorization": "Bearer anything"},
            )
    assert response.status_code == 500


# ---------------------------------------------------------------------------
# Health endpoint remains open
# ---------------------------------------------------------------------------

async def test_health_no_auth_required(client):
    """GET /health works without auth header."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Chat endpoint remains open
# ---------------------------------------------------------------------------

async def test_chat_no_auth_required(client):
    """POST /api/chat works without auth header."""
    with patch(
        "handler.webhooks.call_agent_sync",
        new_callable=AsyncMock,
        return_value="reply",
    ):
        response = await client.post(
            "/api/chat?stream=false",
            json=VALID_PAYLOAD,
        )
    assert response.status_code == 200

"""Tests for handler/webhooks.py FastAPI endpoints."""

import asyncio
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
# Test: lifespan (startup/shutdown + validation)
# ---------------------------------------------------------------------------

async def test_lifespan_caches_agent_engine():
    """Lifespan calls client.agent_engines.get exactly once and caches result."""
    import handler.services as _svc

    mock_client = MagicMock()
    mock_engine = MagicMock()
    mock_client.agent_engines.get.return_value = mock_engine

    with patch("handler.services.Client"):
        from handler.webhooks import lifespan, app as _app

    with patch.object(_svc, "client", mock_client), \
         patch.object(_svc, "_agent_engine", None), \
         patch("handler.auth.WEBHOOK_SECRET", "valid"), \
         patch.object(_svc, "AGENT_ENGINE_ID", "test-engine"):
        async with lifespan(_app):
            assert _svc._agent_engine is mock_engine

        assert _svc._agent_engine is None  # cleaned up on shutdown
        mock_client.agent_engines.get.assert_called_once_with(name="test-engine")


async def test_lifespan_raises_if_webhook_secret_empty():
    """Lifespan raises RuntimeError when WEBHOOK_SECRET is empty."""
    with patch("handler.services.Client"):
        from handler.webhooks import lifespan, app as _app

    with patch("handler.auth.WEBHOOK_SECRET", ""):
        with pytest.raises(RuntimeError, match="WEBHOOK_SECRET"):
            async with lifespan(_app):
                pass


async def test_lifespan_raises_if_agent_engine_id_empty():
    """Lifespan raises RuntimeError when AGENT_ENGINE_ID is empty."""
    import handler.services as _svc

    with patch("handler.services.Client"):
        from handler.webhooks import lifespan, app as _app

    with patch("handler.auth.WEBHOOK_SECRET", "valid"), \
         patch.object(_svc, "AGENT_ENGINE_ID", ""):
        with pytest.raises(RuntimeError, match="AGENT_ENGINE_ID"):
            async with lifespan(_app):
                pass


async def test_lifespan_raises_if_agent_engine_id_bare_prefix():
    """Lifespan catches AGENT_ENGINE_ID expanded from empty bare ID."""
    import handler.services as _svc

    with patch("handler.services.Client"):
        from handler.webhooks import lifespan, app as _app

    with patch("handler.auth.WEBHOOK_SECRET", "valid"), \
         patch.object(_svc, "AGENT_ENGINE_ID", "projects/p/locations/l/reasoningEngines/"):
        with pytest.raises(RuntimeError, match="AGENT_ENGINE_ID"):
            async with lifespan(_app):
                pass


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


async def test_webhook_returns_503_on_agent_error(client):
    """Agent RuntimeError → HTTP 503."""
    with patch(
        "handler.webhooks.call_agent_sync",
        new_callable=AsyncMock,
        side_effect=RuntimeError("vertex AI down"),
    ):
        response = await client.post(
            "/webhook",
            json={"companyId": "c1", "userId": "u1", "message": "hi"},
            headers={"Authorization": f"Bearer {WEBHOOK_TEST_SECRET}"},
        )

    assert response.status_code == 503


async def test_webhook_returns_503_on_timeout(client):
    """Agent timeout → HTTP 503."""
    with patch(
        "handler.webhooks.call_agent_sync",
        new_callable=AsyncMock,
        side_effect=asyncio.TimeoutError,
    ):
        response = await client.post(
            "/webhook",
            json={"companyId": "c1", "userId": "u1", "message": "hi"},
            headers={"Authorization": f"Bearer {WEBHOOK_TEST_SECRET}"},
        )

    assert response.status_code == 503
    assert "tiempo" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Test: docs endpoints disabled
# ---------------------------------------------------------------------------

async def test_docs_endpoint_returns_404(client):
    response = await client.get("/docs")
    assert response.status_code == 404


async def test_redoc_endpoint_returns_404(client):
    response = await client.get("/redoc")
    assert response.status_code == 404


async def test_openapi_json_returns_404(client):
    response = await client.get("/openapi.json")
    assert response.status_code == 404

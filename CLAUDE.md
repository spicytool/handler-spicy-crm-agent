# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

FastAPI handler service for the SpicyTool CRM agent. Sits between chat UI clients and the Vertex AI Agent Engine (`spicytool-crud-agent`), providing auth, session management, and SSE+JSON streaming. Deployed to Cloud Run.

## Commands

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run locally (port 8000, auto-reload)
uvicorn handler.webhooks:app --reload

# Tests
pytest                          # all tests
pytest tests/test_auth.py       # single file
pytest -k test_name             # single test by name
pytest --cov=handler --cov-report=term-missing  # with coverage

# Deploy
./quick-deploy.sh --setup       # first-time Secret Manager setup
./quick-deploy.sh               # build, push, deploy to Cloud Run
```

## Architecture

```
Client request
  → handler/webhooks.py   (FastAPI routes: /health, /api/chat, /webhook)
  → handler/auth.py       (Bearer token verification via WEBHOOK_SECRET)
  → handler/payload.py    (Pydantic v2 request/response models)
  → handler/services.py   (Vertex AI session mgmt + streaming bridge)
  → Vertex AI Agent Engine (remote CRM agent)
```

**Three endpoints:**
- `GET /health` — liveness probe
- `POST /api/chat` — SSE streaming (default) or JSON sync (`?stream=false`). No auth required.
- `POST /webhook` — synchronous JSON, requires `Authorization: Bearer <WEBHOOK_SECRET>`

**Session management** (`services.py`): Sessions are keyed by `companyId:userId`. The handler lists existing sessions via `client.agent_engines.sessions.list` with a filter, reuses the first match, or creates a new one. All calls use a `trace_id` for log correlation.

**Streaming flow**: `call_agent_streaming` → `_find_or_create_session` → `stream_agent_events` (yields text chunks from `async_stream_query`) → SSE `EventSourceResponse` in webhooks.py. Fallback message in Spanish if no chunks produced.

## Key Conventions

- **User-facing messages are in Spanish** (es-419) — fallback/error strings in services.py and webhooks.py
- **User ID format**: `{companyId}:{userId}` — composed in webhooks.py from ChatRequest fields
- **MongoDB $oid coercion**: `payload.py` auto-extracts string from `{"$oid": "..."}` dicts on companyId/userId
- **Secrets**: GCP Secret Manager in prod; `.env` file locally (gitignored). Never hardcode.
- **AGENT_ENGINE_ID**: Required at import time — services.py raises `RuntimeError` if missing. Accepts bare ID or full resource name.
- **Vertex AI client import**: Try `from vertexai import Client`, fall back to `from vertexai._genai.client import Client`

## Testing

- pytest with `asyncio_mode = auto` (pytest.ini)
- `conftest.py` sets required env vars via `monkeypatch` (autouse) and provides mock fixtures for the Vertex AI client
- All Vertex AI calls are mocked — tests never hit GCP
- Test files mirror source: `test_auth.py`, `test_payload.py`, `test_services.py`, `test_webhooks.py`

## Deployment

- **GCP project**: `spicytool-crud-agent`
- **Region**: `us-central1` (never change)
- **Docker**: Python 3.12-slim, runs as non-root `appuser`, port 8080
- **Cloud Run config**: 512Mi memory, 1 CPU, 300s timeout, max 10 instances
- **Artifact Registry**: `us-central1-docker.pkg.dev/spicytool-crud-agent/handler-repo/handler-spicy-crm-agent`

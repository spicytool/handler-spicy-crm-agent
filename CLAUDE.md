# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

FastAPI handler service for the SpicyTool CRM agent. Sits between chat UI clients and the Vertex AI Agent Engine (`spicytool-crud-agent`), providing auth, session management, and JSON responses. Deployed to Cloud Run.

## Commands

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt            # production deps only
pip install -r requirements-dev.txt        # includes test deps (pytest, etc.)

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
  → handler/webhooks.py   (FastAPI routes: /health, /webhook)
  → handler/auth.py       (Bearer token verification via WEBHOOK_SECRET)
  → handler/payload.py    (Pydantic v2 request/response models)
  → handler/services.py   (Vertex AI session mgmt + streaming bridge)
  → Vertex AI Agent Engine (remote CRM agent)
```

**Two endpoints:**
- `GET /health` — liveness probe
- `POST /webhook` — synchronous JSON, requires `Authorization: Bearer <WEBHOOK_SECRET>`. Returns `HTTP 503` on agent errors/timeouts (not 200 with error text). Responses capped at 50,000 characters.

**Startup (lifespan)**: Validates `WEBHOOK_SECRET` and `AGENT_ENGINE_ID` at startup. Caches agent engine via `client.agent_engines.get()` once per app lifecycle. Disables `/docs`, `/redoc`, `/openapi.json` (return 404).

**Session management** (`services.py`): Sessions are keyed by `companyId:userId`. The handler lists existing sessions via `client.agent_engines.sessions.list` with a filter, reuses the first match, or creates a new one. Per-user `asyncio.Lock` prevents duplicate session creation under concurrency. All calls use a `trace_id` for log correlation and 240s timeout via `asyncio.wait_for`.

## Key Conventions

- **User-facing messages are in Spanish** (es-419) — fallback/error strings in services.py and webhooks.py
- **User ID format**: `{companyId}:{userId}` — composed in webhooks.py from ChatRequest fields
- **MongoDB $oid coercion**: `payload.py` auto-extracts string from `{"$oid": "..."}` dicts on companyId/userId
- **Secrets**: GCP Secret Manager in prod; `.env` file locally (gitignored). Never hardcode. `load_dotenv(override=False)` ensures Cloud Run secrets take precedence.
- **AGENT_ENGINE_ID**: Validated at startup in lifespan, not at import time. Accepts bare ID or full resource name. Cached once via `client.agent_engines.get()`.
- **Error signaling**: `call_agent_sync` no longer swallows exceptions — errors propagate as `HTTP 503` to client.
- **PII masking**: `_log_user_id()` strips email from user ID before logging.
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

# Handler Spicy CRM Agent — Research Summary

Research into `spicytool-crud-agent` and `handler-spicy-inbound-agent` to inform the design of this handler service.

---

## 1. The Agent We're Handling: `spicytool-crud-agent`

### Architecture

- **Framework:** Google ADK (`google-adk >=1.15.0,<2.0.0`) — single `LlmAgent` (ReAct), no multi-agent orchestration
- **Model:** `gemini-3-flash-preview` with 3 retry attempts
- **Deployment:** Vertex AI Agent Engine via `AgentEngineApp(AdkApp)` from `google-cloud-aiplatform[agent-engines]==1.130.0`
- **Package manager:** `uv`
- **Python:** `>=3.10,<3.14`

### Agent Capabilities (3 Tools)

| Tool | Description | Key Details |
|------|-------------|-------------|
| `search_contacts` | Search by name/phone/email | Max 10 results, role-based visibility (sellers see assigned only) |
| `create_contact` | Create a new contact | Name required; phone, email, address optional. Agent always searches first |
| `update_contact` | Update existing contact | Requires `contact_id` from prior search. Sellers restricted to assigned contacts |

The agent **cannot** delete contacts — users are told to use the SpicyTool dashboard.

### How to Call the Agent

```python
async for event in agent_engine.async_stream_query(
    message="Search for Juan",
    user_id="<companyId>:<userId>",
):
    # event.content.parts[n].text contains response text
```

- **Streaming:** Native via `async_stream_query` (async generator of ADK `Event` objects)
- **Session management:** Handled internally by ADK — the handler does NOT need to manage session IDs
- **user_id format:** `"<companyId>:<userId>"` (colon-separated MongoDB ObjectId strings)

### Tenant Context Resolution

A `before_agent_callback` fires on every invocation:
1. Splits `user_id` on `:` → `company_id`, `user_id_part`
2. Looks up user role from MongoDB (`companies.colaborators`)
3. Stores `company_id`, `user_id`, `user_role` in ADK session state
4. **If role lookup fails, all tools return an error** — authorization is mandatory

Fallback: if no `:` in `user_id`, uses env vars `SPICY_DEFAULT_COMPANY_ID` and `SPICY_DEFAULT_USER_ID`.

### Additional Operation

`register_feedback(feedback: dict)` — accepts `{score, text, user_id, session_id}` for satisfaction tracking.

### Agent Config

| Env Var | Required | Default |
|---------|----------|---------|
| `MONGODB_URI` | Yes | — |
| `MONGODB_DATABASE` | No | `spicytool` |
| `SPICY_DEFAULT_COMPANY_ID` | No | `""` |
| `SPICY_DEFAULT_USER_ID` | No | `""` |

---

## 2. Reference Handler: `handler-spicy-inbound-agent`

### Architecture

- **Framework:** FastAPI + Uvicorn (ASGI)
- **Language:** Python 3.12
- **Deployment:** Google Cloud Run (512Mi, 1 CPU, 300s timeout, max 10 instances)
- **Docker:** `python:3.12-slim`, non-root user, `WORKDIR /app/handler`

### Module Structure

| File | Responsibility |
|------|----------------|
| `webhooks.py` | FastAPI app, endpoints, lifespan hooks |
| `services.py` | Vertex AI client, session management, streaming, response parsing |
| `payload.py` | Pydantic v2 request/response models |
| `whatsapp.py` | Outbound HTTP client to SpicyTool WhatsApp API |

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhook/whatsapp` | Main message handler |
| `GET` | `/health` | Liveness check |
| `GET` | `/` | Service info |

### Message Flow

```
Inbound webhook → Pydantic validation → Extract last user message
    → Build user_id ({chatBotId}:{phoneNumber})
    → Find/create Vertex AI session
    → async_stream_query() → Accumulate text events
    → Parse JSON response {message, should_escalate}
    → Send reply via SpicyTool WhatsApp API
    → Return WebhookResponse
```

### Agent Engine Communication

```python
from vertexai import Client

client = Client(project=PROJECT_ID, location=LOCATION)
agent_engine = client.agent_engines.get(name=AGENT_ENGINE_ID)

# Session lookup
sessions = client.agent_engines.sessions.list(
    name=AGENT_ENGINE_ID,
    config={"filter": f"user_id={json.dumps(user_id)}"}
)

# Session creation (if none found)
session = client.agent_engines.sessions.create(
    name=AGENT_ENGINE_ID,
    user_id=user_id,
    config={"labels": {"source": "cloudrun"}}
)

# Streaming query
async for event in agent_engine.async_stream_query(
    user_id=user_id, session_id=session_id, message=message
):
    # accumulate text parts
```

### Session Management (Stateless)

- No local session store — fully delegated to Vertex AI Agent Engine
- Sessions identified by `user_id` string
- Lookup: list sessions filtered by `user_id`, sort by `update_time` desc
- Preference: sessions labeled `source: cloudrun` over Playground-created ones
- New sessions labeled `{"source": "cloudrun"}`

### Streaming (Internal Only)

- Streams internally from Agent Engine via `async_stream_query()`
- **Does NOT stream to the caller** — aggregates full response, returns single JSON
- Handles both object-style and dict-style ADK events

### Error Handling Patterns

- Per-request `trace_id` (UUID) for structured log correlation
- `log_kv()` helper for key-value structured logs
- Startup `validate_config()` warns on missing secrets
- Agent call failures → safe fallback response (Spanish error message)
- Session list errors → WARNING, proceeds to create new session
- Outbound send errors → sanitized error responses (no token leakage)

### Config

| Env Var | Required | Default | Source (prod) |
|---------|----------|---------|---------------|
| `SPICY_API_TOKEN` | Yes | — | Secret Manager |
| `SPICYTOOL_API_URL` | No | `https://api-dev.spicytool.net/api/webhooks/whatsApp/sendMessage` | Cloud Run env |
| `GOOGLE_CLOUD_PROJECT` | No | `spicy-inbound-handler` | Cloud Run env |
| `GOOGLE_CLOUD_LOCATION` | No | `us-central1` | Cloud Run env |
| `AGENT_ENGINE_ID` | No | hardcoded resource name | Cloud Run env |
| `DEBUG_AGENT_SESSIONS` | No | Off | Cloud Run env |

### Deployment

- **Platform:** Cloud Run (`--allow-unauthenticated`)
- **Registry:** `us-central1-docker.pkg.dev/spicy-inbound-handler/handler-repo/`
- **Build:** `docker build --platform linux/amd64` (for ARM Macs)
- **Secrets:** `--set-secrets="SPICY_API_TOKEN=SPICY_API_TOKEN:latest"`
- **IAM:** `roles/aiplatform.user`, `roles/secretmanager.secretAccessor`
- **Quick deploy:** `./quick-deploy.sh` handles everything end-to-end

---

## 3. Key Differences for This Handler (CRM Agent vs WhatsApp)

| Aspect | WhatsApp Handler | CRM Agent Handler |
|--------|-----------------|-------------------|
| **Inbound source** | SpicyTool WhatsApp webhook push | SpicyTool frontend chat interface |
| **Outbound delivery** | HTTP POST to SpicyTool WhatsApp send API | Direct response to frontend (likely SSE or standard JSON) |
| **Payload format** | Complex: `chatBotId`, `from`, `conversation[]` with message history | Simpler: likely `companyId`, `userId`, `message` |
| **user_id construction** | `{chatBotId}:{phoneNumber}` | `{companyId}:{userId}` (matches agent's expected format directly) |
| **Response format** | `{status, message_sent, whatsapp_api_status, should_escalate, escalation}` | Simpler: `{message}` or SSE stream |
| **Streaming to client** | No (aggregates internally, sends via separate API) | **Should support streaming** (frontend can render incrementally) |
| **whatsapp.py equivalent** | Calls SpicyTool outbound API with `x-webhook-token` | Not needed if responding directly; or a simpler callback |
| **Webhook auth** | None (open endpoint) | Should implement auth (API key or token validation) |
| **Session management** | Same pattern — Vertex AI sessions by `user_id` | Same pattern — can reuse session find/create logic |
| **Agent Engine ID** | Points to inbound/WhatsApp agent | Points to `spicytool-crud-agent` engine |
| **GCP Project** | `spicy-inbound-handler` | TBD (new project or shared) |

---

## 4. Reusable Patterns from Reference Handler

These patterns from `handler-spicy-inbound-agent` should be carried over:

1. **FastAPI + Uvicorn** — proven stack, same deployment model
2. **Pydantic v2 models** — request/response validation
3. **Vertex AI Client pattern** — `Client(project, location)` → `agent_engines.get()` → `async_stream_query()`
4. **Session management** — stateless, list-by-user_id, create-if-missing, label with `source: cloudrun`
5. **Structured logging** — `trace_id` per request, `log_kv()` helper
6. **Error handling** — safe fallbacks, sanitized error messages, startup config validation
7. **Docker + Cloud Run** — same deployment pipeline, `quick-deploy.sh` pattern
8. **Secret management** — Secret Manager injection via `--set-secrets`

---

## 5. New Considerations for This Handler

1. **Streaming to frontend** — The WhatsApp handler aggregates internally. For a chat UI, we should support **SSE (Server-Sent Events)** so the frontend can render tokens as they arrive.
2. **Webhook authentication** — The WhatsApp handler has none. We should validate inbound requests (API key header or token).
3. **Simpler payload** — No need for WhatsApp-specific fields. The frontend will send `companyId`, `userId`, and `message` directly, which maps cleanly to the agent's `user_id` format.
4. **No outbound send API** — Response goes directly back to the caller, eliminating the `whatsapp.py` module entirely.
5. **Feedback endpoint** — The CRM agent supports `register_feedback()`. We should expose an endpoint for the frontend to submit satisfaction scores.

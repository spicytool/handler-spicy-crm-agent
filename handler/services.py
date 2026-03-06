"""Service functions for processing messages with the deployed CRM agent.

Bridges the FastAPI handler to the Vertex AI Agent Engine via streaming.
"""

import json
import logging
import os
import sys
import uuid
from typing import Any, AsyncGenerator, Optional

try:
    from vertexai import Client  # type: ignore
except Exception:  # pragma: no cover
    from vertexai._genai.client import Client  # type: ignore

# Configure logging for Cloud Run
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "spicy-crm-handler")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

# AGENT_ENGINE_ID — required, no hardcoded fallback
_raw_agent_engine_id = os.getenv("AGENT_ENGINE_ID", "")
if not _raw_agent_engine_id:
    raise RuntimeError("AGENT_ENGINE_ID environment variable is required")

AGENT_ENGINE_ID = (
    _raw_agent_engine_id
    if "/" in _raw_agent_engine_id
    else f"projects/{PROJECT_ID}/locations/{LOCATION}/reasoningEngines/{_raw_agent_engine_id}"
)

client = Client(project=PROJECT_ID, location=LOCATION)


# ---------------------------------------------------------------------------
# Session ID extraction
# ---------------------------------------------------------------------------

def extract_session_id(session: Any) -> Optional[str]:
    """Extract the short session_id from an SDK session object or dict.

    Handles operation wrappers (session.response.name) and direct
    Session objects with a 'name' field containing '/sessions/<id>'.
    """
    if session is None:
        return None

    # Handle long-running operation wrappers (create returns operation).
    response = getattr(session, "response", None) if not isinstance(session, dict) else None
    if response is not None and isinstance(getattr(response, "name", None), str):
        nested = extract_session_id(response)
        if nested:
            return nested

    # Parse from Session.name
    name = session.get("name") if isinstance(session, dict) else getattr(session, "name", None)
    if isinstance(name, str) and name:
        if "/sessions/" in name:
            return name.split("/sessions/")[-1]
        if name.startswith("sessions/"):
            return name.split("/", 1)[-1]
        if "/" not in name:
            return name

    return None


# ---------------------------------------------------------------------------
# Event text extraction
# ---------------------------------------------------------------------------

def extract_text_from_event(event: Any) -> Optional[str]:
    """Extract text from a dict-style ADK event.

    Returns the text string if the event contains a text part,
    or None for function_call, function_response, empty, or invalid events.
    """
    if not isinstance(event, dict):
        return None

    content = event.get("content")
    if not isinstance(content, dict):
        return None

    parts = content.get("parts")
    if not parts or not isinstance(parts, list):
        return None

    for part in parts:
        if not isinstance(part, dict):
            continue
        if "text" in part and part["text"]:
            return part["text"]
        if "function_call" in part or "function_response" in part:
            return None

    return None


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

async def _find_or_create_session(
    user_id: str,
    *,
    trace_id: str,
) -> tuple[Any, str]:
    """Find an existing session for user_id or create one.

    Returns (agent_engine, session_id).
    """
    agent_engine = client.agent_engines.get(name=AGENT_ENGINE_ID)

    filter_expr = f"user_id={json.dumps(user_id)}"
    sessions: list[Any] = []

    logger.info("session_list user_id=%s trace_id=%s", user_id, trace_id)
    try:
        sessions = list(
            client.agent_engines.sessions.list(
                name=AGENT_ENGINE_ID,
                config={"filter": filter_expr},
            )
        )
        logger.info("session_list_done user_id=%s found=%d trace_id=%s", user_id, len(sessions), trace_id)
    except Exception as exc:
        logger.warning("session_list_error user_id=%s error=%s trace_id=%s", user_id, exc, trace_id)

    session_id: Optional[str] = None

    if sessions:
        session_id = extract_session_id(sessions[0])
        logger.info("session_selected id=%s trace_id=%s", session_id, trace_id)

    if not session_id:
        logger.info("session_create user_id=%s trace_id=%s", user_id, trace_id)
        try:
            created = client.agent_engines.sessions.create(
                name=AGENT_ENGINE_ID,
                user_id=user_id,
                ttl="28800s",  # 8-hour session TTL (resets on each interaction)
            )
            session_id = extract_session_id(created)
            logger.info("session_created id=%s trace_id=%s", session_id, trace_id)
        except Exception:
            logger.exception("session_create_error user_id=%s trace_id=%s", user_id, trace_id)
            raise

    return agent_engine, session_id  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

async def stream_agent_events(
    agent_engine: Any,
    user_id: str,
    session_id: str,
    message: str,
    *,
    trace_id: str,
) -> AsyncGenerator[str, None]:
    """Call agent_engine.async_stream_query and yield text chunks."""
    logger.info("query_start user_id=%s session_id=%s trace_id=%s", user_id, session_id, trace_id)

    total_events = 0
    total_text_chunks = 0

    async for event in agent_engine.async_stream_query(
        user_id=user_id,
        session_id=session_id,
        message=message,
    ):
        total_events += 1
        text = extract_text_from_event(event)
        if text:
            total_text_chunks += 1
            yield text

    logger.info(
        "query_done events=%d text_chunks=%d trace_id=%s",
        total_events, total_text_chunks, trace_id,
    )


async def call_agent_streaming(
    user_id: str,
    message: str,
    *,
    trace_id: Optional[str] = None,
) -> AsyncGenerator[str, None]:
    """Resolve session and stream agent response chunks.

    Yields text chunks. If no text was produced, yields a fallback message.
    """
    trace_id = trace_id or uuid.uuid4().hex

    agent_engine, session_id = await _find_or_create_session(user_id, trace_id=trace_id)

    chunks_seen = False
    async for chunk in stream_agent_events(
        agent_engine, user_id, session_id, message, trace_id=trace_id
    ):
        chunks_seen = True
        yield chunk

    if not chunks_seen:
        logger.info("query_fallback user_id=%s trace_id=%s", user_id, trace_id)
        yield "Lo siento, no pude procesar tu mensaje. Podrías intentar de nuevo?"


async def call_agent_sync(
    user_id: str,
    message: str,
    *,
    trace_id: Optional[str] = None,
) -> str:
    """Drive call_agent_streaming and aggregate into a single string."""
    trace_id = trace_id or uuid.uuid4().hex
    try:
        parts: list[str] = []
        async for chunk in call_agent_streaming(user_id, message, trace_id=trace_id):
            parts.append(chunk)
        return "".join(parts)
    except Exception as exc:
        logger.error("call_agent_sync_error user_id=%s error=%s trace_id=%s", user_id, exc, trace_id)
        return "Lo siento, hubo un error al procesar tu mensaje. Por favor intenta de nuevo."

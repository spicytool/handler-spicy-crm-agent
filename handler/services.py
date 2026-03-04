"""Service functions for processing messages with the deployed CRM agent.

Bridges the FastAPI handler to the Vertex AI Agent Engine via streaming.
"""

import os
import json
import logging
import sys
import uuid
from collections import deque
from typing import Optional, Any, AsyncGenerator, Tuple
from datetime import datetime, timezone

try:
    from vertexai import Client  # type: ignore
except Exception:  # pragma: no cover
    from vertexai._genai.client import Client  # type: ignore

from vertexai import agent_engines  # noqa: F401

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

DEBUG_AGENT_SESSIONS = False  # overridden by _env_flag after definition


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------

def _env_flag(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in ("1", "true", "yes", "y", "on")


def _safe_snippet(text: Any, limit: int = 120) -> str:
    if text is None:
        return ""
    cleaned = str(text).replace("\n", "\\n").replace("\r", "\\r")
    return cleaned[:limit]


def _fmt_kv(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return json.dumps(dt.isoformat(), ensure_ascii=False)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(str(value), ensure_ascii=False)


def log_kv(event: str, trace_id: str, level: int = logging.INFO, **fields: Any) -> None:
    parts = [f"event={event}", f"trace_id={trace_id}"]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={_fmt_kv(value)}")
    logger.log(level, " ".join(parts))


# ---------------------------------------------------------------------------
# SDK field helpers
# ---------------------------------------------------------------------------

def _get_field(obj: Any, key: str, default: Any = None) -> Any:
    """Best-effort field extraction for dict-like and object-like SDK returns."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _parse_time(value: Any) -> Optional[datetime]:
    """Parse various timestamp shapes into an aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _session_sort_key(session: Any) -> Tuple[int, float]:
    """Sort sessions by most recent update_time descending."""
    update_time = _parse_time(_get_field(session, "update_time"))
    create_time = _parse_time(_get_field(session, "create_time"))
    best = update_time or create_time
    if not best:
        return (0, 0.0)
    return (1, best.timestamp())


def _extract_session_id(session: Any) -> Optional[str]:
    """Extract the short session_id from an SDK session object or dict."""
    if session is None:
        return None

    # Handle long-running operation wrappers (create returns operation).
    # Only recurse if the response has a string 'name' field (i.e. looks like a Session),
    # to avoid infinite recursion with MagicMock or other proxy objects.
    response = _get_field(session, "response")
    if response is not None and isinstance(_get_field(response, "name"), str):
        response_id = _extract_session_id(response)
        if response_id:
            return response_id

    # Preferred: parse from Session.name.
    name = _get_field(session, "name")
    if isinstance(name, str) and name:
        if "/sessions/" in name:
            return name.split("/sessions/")[-1]
        if name.startswith("sessions/"):
            return name.split("/", 1)[-1]
        if "/" not in name:
            return name

    # Fallbacks for other SDK shapes.
    for key in ("id", "session_id", "sessionId"):
        value = _get_field(session, key)
        if isinstance(value, str) and value:
            return value
    return None


# ---------------------------------------------------------------------------
# Event text extraction
# ---------------------------------------------------------------------------

def extract_text_from_event(event: Any) -> Optional[str]:
    """Extract text from an ADK event (object or dict style).

    Returns the text string if the event contains a text part,
    or None for function_call, function_response, empty, or invalid events.
    """
    if event is None:
        return None

    # Object-style event (ADK Event objects)
    if hasattr(event, "content") and not isinstance(event, dict):
        content = event.content
        if content is None:
            return None
        parts = getattr(content, "parts", None)
        if not parts:
            return None
        for part in parts:
            text = getattr(part, "text", None)
            if text:
                return text
            if getattr(part, "function_call", None) is not None:
                return None
            if getattr(part, "function_response", None) is not None:
                return None
        return None

    # Dict-style event
    if isinstance(event, dict):
        content = event.get("content")
        if not isinstance(content, dict):
            return None
        parts = content.get("parts")
        if not parts or not isinstance(parts, list):
            return None
        for part in parts:
            if isinstance(part, dict):
                if "text" in part and part["text"]:
                    return part["text"]
                if "function_call" in part:
                    return None
                if "function_response" in part:
                    return None
            else:
                text = getattr(part, "text", None)
                if text:
                    return text
        return None

    return None


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

async def _find_or_create_session(
    user_id: str,
    *,
    trace_id: str,
) -> Tuple[Any, str]:
    """Find an existing session for user_id or create one.

    Returns (agent_engine, session_id).
    """
    log_kv("agent_engine_get_start", trace_id, user_id=user_id, agent_engine_id=AGENT_ENGINE_ID)
    agent_engine = client.agent_engines.get(name=AGENT_ENGINE_ID)
    log_kv("agent_engine_get_done", trace_id, agent_engine_id=AGENT_ENGINE_ID)

    filter_expr = f"user_id={json.dumps(user_id)}"
    sessions: list[Any] = []

    log_kv("session_list_start", trace_id, user_id=user_id, filter_expr=filter_expr)
    try:
        sessions = list(
            client.agent_engines.sessions.list(
                name=AGENT_ENGINE_ID,
                config={"filter": filter_expr},
            )
        )
        log_kv("session_list_done", trace_id, user_id=user_id, sessions_found=len(sessions))
    except Exception as e:
        log_kv(
            "session_list_error",
            trace_id,
            level=logging.WARNING,
            user_id=user_id,
            error=str(e),
        )

    session_id: Optional[str] = None

    if sessions:
        sessions.sort(key=_session_sort_key, reverse=True)

        def _label_source(s: Any) -> Optional[str]:
            labels = _get_field(s, "labels")
            if isinstance(labels, dict):
                source = labels.get("source")
                return source if isinstance(source, str) else None
            return None

        cloudrun_sessions = [s for s in sessions if _label_source(s) == "cloudrun"]
        selection_pool = cloudrun_sessions or sessions
        selected = selection_pool[0]
        session_id = _extract_session_id(selected)
        log_kv(
            "session_selected",
            trace_id,
            user_id=user_id,
            selected_session_id=session_id,
            sessions_found=len(sessions),
            sessions_found_cloudrun=len(cloudrun_sessions),
        )

    if not session_id:
        log_kv("session_create_start", trace_id, user_id=user_id)
        try:
            created = client.agent_engines.sessions.create(
                name=AGENT_ENGINE_ID,
                user_id=user_id,
                config={"labels": {"source": "cloudrun"}},
            )
            session_id = _extract_session_id(created)
            log_kv("session_create_done", trace_id, user_id=user_id, created_session_id=session_id)
        except Exception as e:
            log_kv(
                "session_create_error",
                trace_id,
                level=logging.ERROR,
                user_id=user_id,
                error=str(e),
            )
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
    log_kv(
        "query_start",
        trace_id,
        user_id=user_id,
        session_id=session_id,
        message_len=len(message or ""),
        message_snippet=_safe_snippet(message or ""),
    )

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

    log_kv(
        "query_done",
        trace_id,
        user_id=user_id,
        session_id=session_id,
        total_stream_events=total_events,
        total_text_chunks=total_text_chunks,
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
        log_kv("query_fallback", trace_id, user_id=user_id)
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
    except Exception as e:
        log_kv(
            "call_agent_sync_error",
            trace_id,
            level=logging.ERROR,
            user_id=user_id,
            error=str(e),
        )
        return "Lo siento, hubo un error al procesar tu mensaje. Por favor intenta de nuevo."


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

async def submit_feedback(
    user_id: str,
    score: int,
    text: Optional[str] = None,
    session_id: Optional[str] = None,
    *,
    trace_id: Optional[str] = None,
) -> dict:
    """Log user feedback (register_feedback API shape TBD)."""
    trace_id = trace_id or uuid.uuid4().hex
    log_kv(
        "feedback_received",
        trace_id,
        user_id=user_id,
        score=score,
        text=_safe_snippet(text or ""),
        session_id=session_id,
    )
    return {"status": "accepted"}

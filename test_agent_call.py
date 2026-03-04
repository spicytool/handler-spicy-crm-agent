"""Manual integration test: send a message to the CRM agent and log the full response.

This is NOT a pytest test — it requires real GCP credentials and a running agent.
Run directly: python test_agent_call.py
"""

import asyncio
import json
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from vertexai import Client  # noqa: E402

from handler.services import extract_session_id, extract_text_from_event  # noqa: E402

# Config from .env
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
ENGINE_ID = os.getenv("AGENT_ENGINE_ID")
COMPANY_ID = os.getenv("SPICY_DEFAULT_COMPANY_ID")
USER_ID = os.getenv("SPICY_DEFAULT_USER_ID")

# Logging setup
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("test_agent_call")


def _dump(obj):
    """Best-effort JSON dump of an event object."""
    try:
        return json.dumps(dict(obj), default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        pass
    try:
        return json.dumps(vars(obj), default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        pass
    return str(obj)


async def main():
    user_id = f"{COMPANY_ID}:{USER_ID}"
    message = "Hola, busca contactos con nombre Juan"

    log.info("Config: project=%s location=%s", PROJECT_ID, LOCATION)
    log.info("Config: engine_id=%s", ENGINE_ID)
    log.info("Config: user_id=%s", user_id)

    # 1. Init client & get agent engine
    client = Client(project=PROJECT_ID, location=LOCATION)

    log.info("Getting agent engine...")
    agent_engine = client.agent_engines.get(name=ENGINE_ID)
    log.info("Agent engine retrieved: %s", agent_engine)

    # 2. Create session
    log.info("Creating session for user_id=%s", user_id)
    session = client.agent_engines.sessions.create(
        name=ENGINE_ID,
        user_id=user_id,
    )
    session_id = extract_session_id(session)
    log.info("Session created: %s", _dump(session))
    log.info("Session ID: %s", session_id)

    # 3. Stream query
    log.info("Sending message: %r", message)
    event_count = 0
    text_parts = []

    async for event in agent_engine.async_stream_query(
        message=message,
        user_id=user_id,
        session_id=session_id,
    ):
        event_count += 1
        log.debug("EVENT #%d type=%s: %s", event_count, type(event).__name__, _dump(event))

        text = extract_text_from_event(event)
        if text:
            text_parts.append(text)
            log.info("TEXT CHUNK #%d: %s", len(text_parts), text[:200])

    # 4. Summary
    full_response = "".join(text_parts)
    log.info("=== DONE === events=%d text_chunks=%d", event_count, len(text_parts))
    log.info("FULL RESPONSE:\n%s", full_response)


if __name__ == "__main__":
    asyncio.run(main())

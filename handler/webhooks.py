"""FastAPI application for the CRM Agent Handler.

Exposes:
- GET  /health          → liveness probe
- POST /webhook         → SpicyTool interface webhook
"""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException

from handler.payload import (
    ChatRequest,
    WebhookResponse,
)
from handler.auth import verify_webhook_token
from handler.services import call_agent_sync

load_dotenv(override=False)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from handler.auth import WEBHOOK_SECRET
    import handler.services as _svc

    if not WEBHOOK_SECRET:
        raise RuntimeError("WEBHOOK_SECRET environment variable is required")
    if not _svc.AGENT_ENGINE_ID or _svc.AGENT_ENGINE_ID.endswith("/reasoningEngines/"):
        raise RuntimeError("AGENT_ENGINE_ID environment variable is required")

    _svc._agent_engine = _svc.client.agent_engines.get(name=_svc.AGENT_ENGINE_ID)
    logger.info("startup agent_engine_cached")
    yield
    _svc._agent_engine = None
    logger.info("shutdown")


app = FastAPI(
    title="CRM Agent Handler",
    description="Handler for SpicyTool CRM Agent webhook integration",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook", dependencies=[Depends(verify_webhook_token)])
async def webhook(payload: ChatRequest):
    trace_id = uuid.uuid4().hex
    user_id = f"{payload.companyId}:{payload.userId}:{payload.userEmail}"
    try:
        reply = await call_agent_sync(user_id, payload.message, trace_id=trace_id)
    except asyncio.TimeoutError:
        logger.error("agent_timeout trace_id=%s", trace_id)
        raise HTTPException(
            status_code=503,
            detail="El agente no respondió a tiempo. Por favor intenta de nuevo.",
        )
    except Exception as exc:
        logger.error("agent_error trace_id=%s error=%s", trace_id, type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="Error al procesar tu mensaje. Por favor intenta de nuevo.",
        )
    return WebhookResponse(
        companyId=payload.companyId,
        userId=payload.userId,
        message=reply,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

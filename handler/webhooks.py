"""FastAPI application for the CRM Agent Handler.

Exposes:
- GET  /health          → liveness probe
- POST /webhook         → SpicyTool interface webhook
"""

import logging
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI

from handler.payload import (
    ChatRequest,
    WebhookResponse,
)
from handler.auth import verify_webhook_token
from handler.services import call_agent_sync

load_dotenv(override=True)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup")
    yield
    logger.info("shutdown")


app = FastAPI(
    title="CRM Agent Handler",
    description="Handler for SpicyTool CRM Agent webhook integration",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook", dependencies=[Depends(verify_webhook_token)])
async def webhook(payload: ChatRequest):
    trace_id = uuid.uuid4().hex
    user_id = f"{payload.companyId}:{payload.userId}:{payload.userEmail}"
    reply = await call_agent_sync(user_id, payload.message, trace_id=trace_id)
    return WebhookResponse(
        companyId=payload.companyId,
        userId=payload.userId,
        message=reply,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

"""FastAPI application for the CRM Agent Handler.

Exposes:
- GET  /health          → liveness probe
- POST /api/chat        → SSE stream (default) or JSON sync (stream=false)
- POST /webhook         → SpicyTool interface webhook
"""

import json
import logging
import uuid
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from handler.payload import (
    ChatRequest,
    ChatResponse,
    ChatData,
    ErrorResponse,
    ErrorDetail,
    WebhookResponse,
)
from handler.services import call_agent_streaming, call_agent_sync

load_dotenv(override=True)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup")
    yield
    logger.info("shutdown")


app = FastAPI(
    title="CRM Agent Handler",
    description="Handler for SpicyTool CRM Agent chat integration with SSE streaming",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/chat")
async def chat(payload: ChatRequest, stream: bool = True):
    trace_id = uuid.uuid4().hex
    user_id = f"{payload.companyId}:{payload.userId}"

    if stream:
        return EventSourceResponse(_event_generator(user_id, payload.message, trace_id))

    try:
        message = await call_agent_sync(user_id, payload.message, trace_id=trace_id)
        return ChatResponse(data=ChatData(message=message))
    except Exception as exc:
        logger.error("chat_error trace_id=%s error=%s", trace_id, exc)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                error=ErrorDetail(code="agent_error", message="Error al procesar tu solicitud")
            ).model_dump(),
        )


async def _event_generator(user_id: str, message: str, trace_id: str):
    try:
        async for chunk in call_agent_streaming(user_id, message, trace_id=trace_id):
            yield {"data": json.dumps({"text": chunk})}
        yield {"data": "[DONE]"}
    except Exception as exc:
        logger.error("sse_error trace_id=%s error=%s", trace_id, exc)
        yield {
            "event": "error",
            "data": json.dumps(
                {"code": "agent_error", "message": "Error al procesar tu solicitud"}
            ),
        }


@app.post("/webhook")
async def webhook(payload: ChatRequest):
    trace_id = uuid.uuid4().hex
    user_id = f"{payload.companyId}:{payload.userId}"
    reply = await call_agent_sync(user_id, payload.message, trace_id=trace_id)
    return WebhookResponse(
        companyId=payload.companyId,
        userId=payload.userId,
        message=reply,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

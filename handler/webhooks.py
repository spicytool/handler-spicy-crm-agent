"""FastAPI application for the CRM Agent Handler.

Exposes:
- GET  /health          → liveness probe
- POST /api/chat        → SSE stream (default) or JSON sync (stream=false)
- POST /api/feedback    → submit user feedback
"""

import json
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
    FeedbackRequest,
    FeedbackResponse,
    FeedbackData,
    ErrorResponse,
    ErrorDetail,
)
from handler.services import call_agent_streaming, call_agent_sync, submit_feedback, log_kv

load_dotenv(override=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    trace_id = uuid.uuid4().hex
    log_kv("startup", trace_id)
    yield
    log_kv("shutdown", trace_id)


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
    except Exception as e:
        log_kv("chat_error", trace_id, error=str(e))
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
    except Exception as e:
        log_kv("sse_error", trace_id, error=str(e))
        yield {
            "event": "error",
            "data": json.dumps(
                {"code": "agent_error", "message": "Error al procesar tu solicitud"}
            ),
        }


@app.post("/api/feedback", status_code=201)
async def feedback(payload: FeedbackRequest):
    trace_id = uuid.uuid4().hex
    user_id = f"{payload.companyId}:{payload.userId}"
    await submit_feedback(
        user_id=user_id,
        score=payload.score,
        text=payload.text,
        session_id=payload.sessionId,
        trace_id=trace_id,
    )
    return FeedbackResponse(data=FeedbackData(status="submitted"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

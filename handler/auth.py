"""Bearer token authentication for webhook endpoints."""

import hmac
import os

from fastapi import Depends, HTTPException, Request

WEBHOOK_SECRET = (
    os.environ.get("WEBHOOK_SECRET_PRODUCTION")
    or os.environ.get("WEBHOOK_SECRET_LOCAL", "")
)


async def verify_webhook_token(request: Request) -> None:
    """Validate Authorization: Bearer <token> header against WEBHOOK_SECRET.

    Raises HTTPException 401 if the token is missing or invalid.
    Uses hmac.compare_digest for timing-safe comparison.
    """
    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Server misconfigured")

    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = auth_header[7:]  # strip "Bearer "
    if not hmac.compare_digest(token, WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Unauthorized")

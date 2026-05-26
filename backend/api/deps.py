"""Shared API dependencies."""
from __future__ import annotations

from fastapi import Header, HTTPException, status

from ..config import settings


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Mutating endpoints require X-API-Key when one is configured.

    No-op when `JOBPULSE_API_KEY` is unset (local-only default).
    """
    expected = settings.api_key
    if not expected:
        return
    if not x_api_key or x_api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad API key")

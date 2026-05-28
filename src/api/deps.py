"""Dependencias FastAPI: autenticación por API key."""
from __future__ import annotations

from fastapi import Header, HTTPException, status

from src.config import settings


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida o ausente (cabecera X-API-Key).",
        )

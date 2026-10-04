"""Centralised error types and FastAPI exception handlers."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class ParcelAIError(Exception):
    """Base error for all application-level exceptions."""

    status_code: int = 500

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class NotFoundError(ParcelAIError):
    """Raised when a requested resource does not exist."""

    status_code = 404


class ValidationError(ParcelAIError):
    """Raised when user-supplied data fails validation."""

    status_code = 422


class ConflictError(ParcelAIError):
    """Raised on optimistic-concurrency conflicts (stale updated_at)."""

    status_code = 409


class IngestError(ParcelAIError):
    """Raised when raster/vector ingestion, reprojection or alignment fails."""

    status_code = 400


class InferenceError(ParcelAIError):
    """Raised when model inference fails."""

    status_code = 500


class TopologyError(ParcelAIError):
    """Raised on topological validation and geometry errors."""

    status_code = 400


async def parcelai_exception_handler(request: Request, exc: ParcelAIError) -> JSONResponse:
    """Convert ParcelAIError subclasses into structured JSON responses."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": type(exc).__name__, "detail": exc.detail},
    )

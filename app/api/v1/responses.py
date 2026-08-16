"""Shared FastAPI route helpers."""

from fastapi import status

from app.schemas.company import ErrorResponse

ERROR_RESPONSES = {
    status.HTTP_400_BAD_REQUEST: {
        "model": ErrorResponse,
        "description": "Business validation error",
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "Resource not found",
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponse,
        "description": "Conflict with current state",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "description": "Request validation error",
    },
    status.HTTP_500_INTERNAL_SERVER_ERROR: {
        "model": ErrorResponse,
        "description": "Unexpected server error",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": "Required dependency unavailable",
    },
}

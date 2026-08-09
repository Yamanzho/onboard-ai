from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)


def register_exception_handlers(app: FastAPI) -> None:
    """Register application-wide HTTP exception handlers."""

    @app.exception_handler(NotFoundError)
    async def not_found_handler(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": exc.message},
        )

    @app.exception_handler(ForbiddenError)
    async def forbidden_handler(_: Request, exc: ForbiddenError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": exc.message},
        )

    @app.exception_handler(ConflictError)
    async def conflict_handler(_: Request, exc: ConflictError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": exc.message},
        )

    @app.exception_handler(ValidationError)
    async def validation_error_handler(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": exc.message},
        )

    @app.exception_handler(ServiceUnavailableError)
    async def service_unavailable_handler(
        _: Request,
        exc: ServiceUnavailableError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": exc.message},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "detail": jsonable_encoder(
                    exc.errors(),
                    custom_encoder={Exception: str},
                )
            },
        )

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"detail": exc.message},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

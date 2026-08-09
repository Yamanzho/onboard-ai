"""Domain and application errors mapped to HTTP by the API layer."""


class AppError(Exception):
    """Base application error."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotFoundError(AppError):
    """Requested entity does not exist."""


class ConflictError(AppError):
    """Request conflicts with current state (e.g. unique constraint)."""


class ValidationError(AppError):
    """Business rule or domain invariant was violated."""


class ForbiddenError(AppError):
    """Caller is authenticated but not permitted to perform this action."""


class UnauthorizedError(AppError):
    """Caller is missing or has invalid credentials."""


class ServiceUnavailableError(AppError):
    """Required dependency unavailable (e.g. Redis in production)."""

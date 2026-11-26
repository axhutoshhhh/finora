"""Typed application exceptions mapped consistently to HTTP error responses."""

from __future__ import annotations


class FinoraError(Exception):
    """Base error with machine-readable code, HTTP status, and optional field."""

    status_code: int = 400
    code: str = "finora_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.field = field

    def to_dict(self) -> dict[str, dict[str, str]]:
        payload: dict[str, str] = {
            "code": self.code,
            "message": self.message,
        }
        if self.field:
            payload["field"] = self.field
        return {"error": payload}


class ValidationError(FinoraError):
    """Input validation or domain rule failure."""

    status_code = 400
    code = "validation_error"


class NotFoundError(FinoraError):
    """Requested resource does not exist or is unavailable."""

    status_code = 404
    code = "not_found"


class ConflictError(FinoraError):
    """Idempotency or state conflict."""

    status_code = 409
    code = "conflict"


class DatabaseError(FinoraError):
    """Internal persistence failure (never exposes raw SQL details)."""

    status_code = 500
    code = "database_error"

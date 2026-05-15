from __future__ import annotations
from typing import Any
from rest_framework import status as drf_status
from rest_framework.views import exception_handler
from rest_framework.response import Response


class AppError(Exception):
    """
    Base exception for all domain service errors.
    All app-level exception hierarchies should inherit from this.
    The global handler catches AppError, so new apps require zero changes here.
    """
    status_code: int = drf_status.HTTP_400_BAD_REQUEST

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}
        if status_code is not None:
            self.status_code = status_code


def custom_exception_handler(exc, context):
    if isinstance(exc, AppError):
        return Response(
            {"error": exc.message, "details": exc.details},
            status=exc.status_code,
        )
    return exception_handler(exc, context)
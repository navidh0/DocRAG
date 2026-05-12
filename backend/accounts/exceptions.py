from __future__ import annotations

from typing import Any
from rest_framework import status


class AccountsServiceError(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str, status_code: int | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}
        if status_code is not None:
            self.status_code = status_code


class UserAlreadyExistsError(AccountsServiceError):
    status_code: int = status.HTTP_409_CONFLICT

    def __init__(self, field: str = "email") -> None:
        super().__init__(
            message="A user with this credential already exists.",
            details={field: "Already in use."},
        )


class UserNotFoundError(AccountsServiceError):
    status_code: int = status.HTTP_404_NOT_FOUND

    def __init__(self) -> None:
        super().__init__(message="User not found.")


class InvalidTokenError(AccountsServiceError):
    status_code: int = status.HTTP_400_BAD_REQUEST

    def __init__(self) -> None:
        super().__init__(message="Invalid or expired token.")


class MissingRefreshTokenError(AccountsServiceError):
    status_code: int = status.HTTP_400_BAD_REQUEST

    def __init__(self) -> None:
        super().__init__(
            message="Refresh token is missing.",
            details={"refresh": "Token not found in cookie."},
        )
from rest_framework import status

class AccountsServiceError(Exception):
    """
    Base exception for all accounts-domain service errors.
    Caught by core.exceptions.custom_exception_handler.
    """

    def __init__(self, message: str, details: dict | None = None, status_code: int = status.HTTP_400_BAD_REQUEST):
        self.message = message
        self.details = details or {}
        self.status_code = status_code
        super().__init__(message)


class UserAlreadyExistsError(AccountsServiceError):
    def __init__(self, field: str = "email"):
        super().__init__(
            message="A user with this credential already exists.",
            details={field: "Already in use."},
            status_code=status.HTTP_409_CONFLICT,
        )


class InvalidTokenError(AccountsServiceError):
    def __init__(self):
        super().__init__(
            message="Invalid or expired token.",
            details={},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class MissingRefreshTokenError(AccountsServiceError):
    def __init__(self):
        super().__init__(
            message="Refresh token is missing.",
            details={"refresh": "Token not found in cookie."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
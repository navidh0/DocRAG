from __future__ import annotations

import logging

from rest_framework_simplejwt.tokens import RefreshToken

from ..exceptions import (
    InvalidTokenError,
    MissingRefreshTokenError,
    UserAlreadyExistsError,
)
from accounts.models import User
from accounts.selectors import user_email_exists, user_username_exists

logger = logging.getLogger(__name__)


def register_user(*, username: str, email: str, password: str) -> User:
    if user_email_exists(email=email):
        raise UserAlreadyExistsError(field="email")

    if user_username_exists(username=username):
        raise UserAlreadyExistsError(field="username")

    user = User.objects.create_user(username=username, email=email, password=password)
    logger.info("New user registered: %s (id=%s)", user.email, user.id)
    return user


def update_user_profile(*, user: User, username: str | None = None, email: str | None = None) -> User:
    if email and user_email_exists(email=email, exclude_user_id=user.pk):
        raise UserAlreadyExistsError(field="email")

    if username and user_username_exists(username=username, exclude_user_id=user.pk):
        raise UserAlreadyExistsError(field="username")

    if email:
        user.email = email
    if username:
        user.username = username

    user.save(update_fields=["email", "username", "updated_at"])
    logger.info("User profile updated: id=%s", user.id)
    return user


def logout_user(*, refresh_token: str | None) -> None:
    if not refresh_token:
        raise MissingRefreshTokenError()

    try:
        token = RefreshToken(refresh_token)
        token.blacklist()
        logger.info("Refresh token blacklisted.")
    except Exception:
        raise InvalidTokenError()
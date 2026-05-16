from django.db.models import QuerySet

from .exceptions import UserNotFoundError
from .models import User


def get_user_by_id(*, user_id) -> User:
    try:
        return User.objects.get(pk=user_id)
    except User.DoesNotExist:
        raise UserNotFoundError()


def user_email_exists(*, email: str, exclude_user_id=None) -> bool:
    qs = User.objects.filter(email=email)
    if exclude_user_id is not None:
        qs = qs.exclude(pk=exclude_user_id)
    return qs.exists()


def user_username_exists(*, username: str, exclude_user_id=None) -> bool:
    qs = User.objects.filter(username=username)
    if exclude_user_id is not None:
        qs = qs.exclude(pk=exclude_user_id)
    return qs.exists()


def get_all_users() -> QuerySet[User]:
    return User.objects.all()
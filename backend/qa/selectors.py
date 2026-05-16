from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict, cast
from uuid import UUID

from django.utils import timezone

from .exceptions import QuestionActivityNotFoundError
from .filters import QuestionActivityFilter
from .models import QuestionActivity

if TYPE_CHECKING:
    from accounts.models import User


class QuestionActivityListFilters(TypedDict, total=False):
    """
    Typed contract between the filter serializer and the selector.
    Each key maps 1-to-1 to a field on QuestionActivityFilter.
    Extend here (and in filters.py + serializers.py) as new filters are added.
    The implemention is similar to the document domain.
    """
    status: str
    document_id: UUID


def question_activity_list(
    *,
    user: User,
    filters: QuestionActivityListFilters | None = None,
):
    raw: dict[str, Any] = cast(dict[str, Any], filters) if filters else {}
    qs = QuestionActivity.objects.filter(user=user).order_by("-created_at")
    return QuestionActivityFilter(raw, queryset=qs).qs


def question_activity_get(*, user: User, activity_id: UUID) -> QuestionActivity:
    try:
        return QuestionActivity.objects.get(id=activity_id, user=user)
    except QuestionActivity.DoesNotExist:
        raise QuestionActivityNotFoundError(
            "Question activity not found.",
            details={"activity_id": str(activity_id)},
        )


def question_activity_stats(*, user: User) -> dict:
    return {
        "questions_today": QuestionActivity.objects.filter(
            user=user,
            created_at__date=timezone.now().date(),
        ).count(),
    }
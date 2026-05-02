# qa/selectors.py
from __future__ import annotations
from typing import TYPE_CHECKING
from uuid import UUID

import django_filters
from django.utils import timezone

from .exceptions import QuestionActivityNotFoundError
from .models import QuestionActivity

if TYPE_CHECKING:
    from accounts.models import User


class QuestionActivityFilter(django_filters.FilterSet):
    class Meta:
        model = QuestionActivity
        fields = {
            "status": ["exact"],
            "document_id": ["exact"],
        }


def question_activity_list(*, user: User, filters: dict | None = None):
    filters = filters or {}

    doc_id = filters.get("document_id")
    if doc_id:
        from documents.models import Document

        if not Document.objects.filter(id=doc_id, user=user).exists():
            raise QuestionActivityNotFoundError(
                "Document not found or does not belong to you.",
                details={"document_id": str(doc_id)},
            )

    qs = QuestionActivity.objects.filter(user=user).order_by("-created_at")
    return QuestionActivityFilter(filters, queryset=qs).qs


def question_activity_get(*, user: "User", activity_id: UUID) -> QuestionActivity:
    try:
        return QuestionActivity.objects.get(id=activity_id, user=user)
    except QuestionActivity.DoesNotExist:
        raise QuestionActivityNotFoundError(
            "Question activity not found.",
            details={"activity_id": str(activity_id)},
        )


def question_activity_stats(*, user: "User") -> dict:
    return {
        "questions_today": QuestionActivity.objects.filter(
            user=user,
            created_at__date=timezone.now().date(),
        ).count(),
    }
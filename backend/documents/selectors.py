from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict, cast
from uuid import UUID

from django.db.models import QuerySet

from .exceptions import DocumentNotFoundError
from .filters import DocumentFilter
from .models import Document

if TYPE_CHECKING:
    from accounts.models import User


class DocumentListFilters(TypedDict, total=False):
    search: str
    file_type: str
    status: str


def document_list(
    *,
    user: User,
    filters: DocumentListFilters | None = None,
) -> QuerySet[Document]:
    qs = Document.objects.filter(user=user).order_by("-created_at")
    return DocumentFilter(cast(dict, filters) or {}, queryset=qs).qs


def document_get(*, user: User, document_id: UUID) -> Document:
    try:
        return Document.objects.get(id=document_id, user=user)
    except Document.DoesNotExist:
        raise DocumentNotFoundError("Document not found")
from __future__ import annotations
from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import QuerySet
import django_filters

from .models import Document

if TYPE_CHECKING:
    from accounts.models import User
class DocumentFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(field_name='file_name', lookup_expr='icontains')
    class Meta:
        model = Document
        fields = {
            'file_type': ['exact'],
            'status': ['exact'],
            'file_name': ['icontains'],
        }

def document_list(*, user: User, filters: dict[str, str] | None = None) -> QuerySet[Document]:
    qs = Document.objects.filter(user=user).order_by('-created_at')
    return DocumentFilter(filters, queryset=qs).qs

def document_get(*, user: User, document_id: UUID) -> Document:
    from .services import DocumentNotFoundError
    try:
        return Document.objects.get(id=document_id, user=user)
    except Document.DoesNotExist:
        raise DocumentNotFoundError("Document not found")
from __future__ import annotations

import django_filters

from .models import Document


class DocumentFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(
        field_name="file_name",
        lookup_expr="icontains",
    )

    class Meta:
        model = Document
        fields = {
            "file_type": ["exact"],
            "status": ["exact"],
        }
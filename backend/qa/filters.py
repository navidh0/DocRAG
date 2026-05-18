from __future__ import annotations

import django_filters

from .models import QuestionActivity


class QuestionActivityFilter(django_filters.FilterSet):
    """
    FilterSet for QuestionActivity. Uses explicit field declarations (not
    Meta.fields dict shorthand) so future filters — date ranges, ordering,
    full-text search — are one field away without restructuring the class.
    """

    status = django_filters.ChoiceFilter(
        choices=QuestionActivity.STATUS_CHOICES,
        # Rejects values outside choices at the ORM level; consistent with
        # the model's own STATUS_CHOICES definition.
    )
    document_id = django_filters.UUIDFilter(
        field_name="document_id",
    )
    
    class Meta:
        model = QuestionActivity
        fields = ["status", "document_id"]
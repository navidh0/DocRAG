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

    # ---------------------------------------------------------------------------
    # Future-ready slots (uncomment and extend as the feature set grows)
    # ---------------------------------------------------------------------------
    # created_at_date = django_filters.DateFilter(
    #     field_name="created_at", lookup_expr="date"
    # )
    # created_at_after = django_filters.DateTimeFilter(
    #     field_name="created_at", lookup_expr="gte"
    # )
    # created_at_before = django_filters.DateTimeFilter(
    #     field_name="created_at", lookup_expr="lte"
    # )
    # ordering = django_filters.OrderingFilter(
    #     fields=["created_at", "response_time_ms", "status"]
    # )

    class Meta:
        model = QuestionActivity
        fields = ["status", "document_id"]
from __future__ import annotations

from rest_framework import serializers

from .models import QuestionActivity

# ---------------------------------------------------------------------------
# Module-level constants
# Derived from the model so there is exactly one source of truth.
# ---------------------------------------------------------------------------

STATUS_CHOICES = [choice[0] for choice in QuestionActivity.STATUS_CHOICES]
# → ['success', 'no_answer', 'error']


# ---------------------------------------------------------------------------
# Input Serializers — validation only, no representation logic
# ---------------------------------------------------------------------------


class AskQuestionInputSerializer(serializers.Serializer):
    question = serializers.CharField(required=True)
    document_id = serializers.UUIDField(required=False, allow_null=False)
    page = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate_question(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Question must not be blank.")
        return value


class StreamQuestionInputSerializer(serializers.Serializer):
    question = serializers.CharField(required=True)
    document_id = serializers.UUIDField(required=False, allow_null=False)

    def validate_question(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Question must not be blank.")
        return value


class QuestionActivityListFilterSerializer(serializers.Serializer):
    """
    Validates and coerces query parameters for the activity list endpoint.
    Validated data is passed directly to QuestionActivityFilter in the selector.
    Mirrors DocumentListFilterSerializer in the documents app.
    """

    status = serializers.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        help_text="Filter by question outcome.",
    )
    document_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text=(
            "Scope history to a specific document. "
            "Returns 404 if the document does not belong to the authenticated user."
        ),
    )


# ---------------------------------------------------------------------------
# Output Serializers — representation only, no validation logic
# ---------------------------------------------------------------------------


class AskQuestionOutputSerializer(serializers.Serializer):
    task_id = serializers.CharField()
    status = serializers.CharField()


class SourceSerializer(serializers.Serializer):
    file_name = serializers.CharField()
    page = serializers.IntegerField()
    chunk_index = serializers.IntegerField()
    excerpt = serializers.CharField()


class QuestionResultOutputSerializer(serializers.Serializer):
    task_id = serializers.CharField()
    status = serializers.CharField()
    answer = serializers.CharField(required=False)
    sources = SourceSerializer(many=True, required=False)
    response_time_ms = serializers.IntegerField(required=False)


class QuestionActivityOutputSerializer(serializers.ModelSerializer):
    sources_count = serializers.SerializerMethodField()

    class Meta:
        model = QuestionActivity
        fields = [
            "id",
            "task_id",
            "question",
            "answer",
            "document_id",
            "sources_count",
            "response_time_ms",
            "status",
            "created_at",
        ]
        read_only_fields = fields

    def get_sources_count(self, instance: QuestionActivity) -> int:
        return len(instance.sources)


class QuestionActivityStatsSerializer(serializers.Serializer):
    """
    Kept for potential future dedicated stats endpoint.
    Not used by the list view — the paginator builds that envelope directly.
    """

    questions_today = serializers.IntegerField()
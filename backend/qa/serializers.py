# qa/serializers.py
from rest_framework import serializers

from .models import QuestionActivity


# ---------------------------------------------------------------------------
# Input Serializers — validation only, no representation logic
# ---------------------------------------------------------------------------

class AskQuestionInputSerializer(serializers.Serializer):
    question = serializers.CharField(required=True)
    document_id = serializers.UUIDField(required=False, allow_null=True)
    page = serializers.IntegerField(required=False, allow_null=True, min_value=1)

    def validate_question(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Question must not be blank.")
        return value


class StreamQuestionInputSerializer(serializers.Serializer):
    question = serializers.CharField(required=True)
    document_id = serializers.UUIDField(required=False, allow_null=True)

    def validate_question(self, value: str) -> str:
        if not value.strip():
            raise serializers.ValidationError("Question must not be blank.")
        return value


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
    total_questions = serializers.IntegerField()
    questions_today = serializers.IntegerField()
from __future__ import annotations

from rest_framework import serializers
from .models import Document

ALLOWED_EXTENSIONS = {'pdf', 'xlsx', 'xls', 'txt', 'csv'}

STATUS_CHOICES = ['pending', 'processing', 'completed', 'failed']
FILE_TYPE_CHOICES = ['pdf', 'xlsx', 'xls', 'txt', 'csv']


# =========================
# INPUT SERIALIZERS
# =========================

class DocumentUploadInputSerializer(serializers.Serializer):
    file = serializers.FileField()

    def validate(self, attrs):
        file = attrs['file']
        ext = file.name.rsplit('.', 1)[-1].lower() if '.' in file.name else ''

        if ext not in ALLOWED_EXTENSIONS:
            raise serializers.ValidationError({
                "file": f"Unsupported file type: .{ext}. Allowed: {sorted(ALLOWED_EXTENSIONS)}"
            })

        attrs['file_name'] = file.name
        attrs['file_type'] = ext
        return attrs


class DocumentListFilterSerializer(serializers.Serializer):
    """
    Validates and coerces query parameters for document list filtering.
    Validated data is passed directly to DocumentFilter in the selector.
    """
    search = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Case-insensitive partial match against file name.",
    )
    file_type = serializers.ChoiceField(
        choices=FILE_TYPE_CHOICES,
        required=False,
        help_text="Exact match against file type.",
    )
    status = serializers.ChoiceField(
        choices=STATUS_CHOICES,
        required=False,
        help_text="Exact match against processing status.",
    )


# =========================
# OUTPUT SERIALIZERS
# =========================

class DocumentOutputSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = ('id', 'file', 'file_name', 'file_type', 'status', 'created_at')
        read_only_fields = fields


class DocumentStatusOutputSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    file_name = serializers.CharField()
    status = serializers.CharField()
    created_at = serializers.CharField()
    status_description = serializers.CharField()


class DocumentChunkMetadataSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    document_id = serializers.UUIDField()
    file_name = serializers.CharField()
    source = serializers.CharField(required=False, allow_null=True)
    page = serializers.IntegerField(required=False, allow_null=True)


class DocumentChunkSerializer(serializers.Serializer):
    content = serializers.CharField(
        help_text="First 150 characters of the chunk content."
    )
    metadata = DocumentChunkMetadataSerializer()


class DocumentStatusWithChunksOutputSerializer(DocumentStatusOutputSerializer):
    total_chunks = serializers.IntegerField()
    chunks = DocumentChunkSerializer(many=True)
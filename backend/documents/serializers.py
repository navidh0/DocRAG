from rest_framework import serializers
from .models import Document

ALLOWED_EXTENSIONS = {'pdf', 'xlsx', 'xls', 'txt', 'csv'}

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
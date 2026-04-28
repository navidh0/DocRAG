import django_filters
from .models import Document

class DocumentFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(field_name='file_name', lookup_expr='icontains')
    class Meta:
        model = Document
        fields = {
            'file_type': ['exact'],
            'status': ['exact'],
            'file_name': ['icontains'],
        }

def document_list(*, user, filters=None):
    qs = Document.objects.filter(user=user).order_by('-created_at')
    return DocumentFilter(filters, queryset=qs).qs

def document_get(*, user, document_id):
    from .services import DocumentNotFoundError
    try:
        return Document.objects.get(id=document_id, user=user)
    except Document.DoesNotExist:
        raise DocumentNotFoundError("Document not found")
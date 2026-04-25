from .models import Document


def document_list(*, user):
    return Document.objects.filter(user=user)


def document_get(*, user, document_id):
    from .services import DocumentNotFoundError
    try:
        return Document.objects.get(id=document_id, user=user)
    except Document.DoesNotExist:
        raise DocumentNotFoundError("Document not found")
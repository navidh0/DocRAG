from celery import shared_task
from uuid import UUID

@shared_task
def process_document_embedding(doc_id: UUID):
    from .services import ProcessDocumentService
    ProcessDocumentService.execute(document_id=doc_id)
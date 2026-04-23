from celery import shared_task

@shared_task
def process_document_embedding(doc_id):
    from .services import ProcessDocumentService
    ProcessDocumentService.execute(doc_id)
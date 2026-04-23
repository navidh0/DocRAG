import os
import ollama

from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from django.conf import settings
from rest_framework import status

from langchain_postgres import PGVector
from langchain_community.document_loaders import PyMuPDFLoader, UnstructuredExcelLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document as LCDocument

from .models import Document
from .utils import get_vector_store_connection

# =========================
# ERROR HANDLING
# =========================
class DocumentsServicesError(Exception):
    """Base exception class for all document service specific errors."""
    
    status_code = status.HTTP_400_BAD_REQUEST
    
    def __init__(self, message, status_code=None, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        if status_code is not None:
            self.status_code = status_code
class DocumentNotFoundError(DocumentsServicesError):
    """Raised when a specific document ID cannot be found."""
    status_code = status.HTTP_404_NOT_FOUND

class DocumentProcessingError(DocumentsServicesError):
    """Raised when document processing fails (e.g., file format invalid)."""
    status_code = status.HTTP_400_BAD_REQUEST


# =========================
# CREATE DOCUMENT
# =========================

class CreateDocumentService:
    @staticmethod
    def execute(*, user, validated_data):
        doc = Document.objects.create(user=user, **validated_data)

        from .tasks import process_document_embedding

        transaction.on_commit(
            lambda: process_document_embedding.delay(str(doc.id))
        )

        return doc


# =========================
# DELETE DOCUMENT
# =========================

class DeleteDocumentService:
    @staticmethod
    def execute(*, user, document_id):
        doc = Document.objects.get(id=document_id, user=user)

        data = {
            "id": str(doc.id),
            "file_name": doc.file_name
        }

        doc.delete()
        return data


# =========================
# DOCUMENT STATUS
# =========================

class GetDocumentStatusService:

    STATUS_DESCRIPTIONS = {
        'pending': 'Waiting to be processed',
        'processing': 'Extracting text and generating embeddings...',
        'completed': 'Ready for Q&A',
        'failed': 'Processing failed. Check file format or logs.',
    }

    @classmethod
    def execute(cls, *, user, document_id):
        try:
            doc = Document.objects.get(id=document_id, user=user)
        except ObjectDoesNotExist:
            return None

        return {
            "id": str(doc.id),
            "file_name": doc.file_name,
            "status": doc.status,
            "created_at": doc.created_at.isoformat(),
            "status_description": cls.STATUS_DESCRIPTIONS.get(doc.status, "Unknown")
        }


# =========================
# DEBUG CHUNKS
# =========================

class DebugDocumentChunksService:
    @staticmethod
    def execute(*, user, document_id):
        connection = get_vector_store_connection()

        store = PGVector(
            collection_name="rag_collection",
            connection=connection,
            embeddings=None,
            use_jsonb=True,
        )

        client = ollama.Client(host=settings.OLLAMA_BASE_URL)

        response = client.embed(
            model=settings.OLLAMA_EMBED_MODEL,
            input="document"
        )

        query_vector = response['embeddings'][0]
        try:
            chunks = store.similarity_search_by_vector(
                embedding=query_vector,
                k=settings.TOP_K_CHUNKS,
                filter={
                    "document_id": str(document_id),
                    "user_id": str(user.id)
                }
            )
        except Exception as e:
            raise RuntimeError(f"Vector search failed: {e}")
        
        return {
            "document_id": document_id,
            "total_chunks_found": len(chunks),
            "chunks": [
                {
                    "content": c.page_content[:150],
                    "metadata": c.metadata
                }
                for c in chunks
            ]
        }


# =========================
# PROCESS DOCUMENT (CORE)
# =========================

class ProcessDocumentService:

    @staticmethod
    def execute(document_id):
        print(f"[SERVICE] Processing document {document_id}")

        updated = Document.objects.filter(
            id=document_id,
            status='pending'
        ).update(status='processing')

        if updated == 0:
            return

        doc = Document.objects.get(id=document_id)

        try:
            data = ProcessDocumentService._load_document(doc)
            splits = ProcessDocumentService._split_document(data)
            texts = [split.page_content for split in splits]
            if not texts:
                raise ValueError("Document contains no extractable text")
            
            embeddings = ProcessDocumentService._generate_embeddings(texts)
            ProcessDocumentService._store_embeddings(doc, splits, texts, embeddings)

            doc.status = 'completed'

        except Exception as e:
            print(f"[SERVICE ERROR][Document {document_id}] {e}")
            import traceback
            traceback.print_exc()
            doc.status = 'failed'

        doc.save()

    # -------------------------
    # INTERNAL HELPERS
    # -------------------------

    @staticmethod
    def _load_document(doc):
        file_name = doc.file_name.lower()
        if file_name.endswith('.pdf'):
            loader = PyMuPDFLoader(doc.file.path)
            return loader.load()

        elif file_name.endswith(('.xlsx', '.xls')):
            loader = UnstructuredExcelLoader(doc.file.path, mode="elements")
            return loader.load()

        elif file_name.endswith(('.txt', '.csv')):
            with open(doc.file.path, 'r', encoding='utf-8') as f:
                text = f.read()

            return [
                LCDocument(
                    page_content=text,
                    metadata={"source": doc.file_name}
                )
            ]

        else:
            raise ValueError(f"Unsupported file type: {doc.file_name}")

    @staticmethod
    def _split_document(data):
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP
        )
        return splitter.split_documents(data)

    @staticmethod
    def _generate_embeddings(texts):
        client = ollama.Client(host=settings.OLLAMA_BASE_URL)

        response = client.embed(
            model=settings.OLLAMA_EMBED_MODEL,
            input=texts
        )

        return response['embeddings']

    @staticmethod
    def _store_embeddings(doc, splits, texts, embeddings):
        connection = get_vector_store_connection()

        store = PGVector(
            collection_name="rag_collection",
            connection=connection,
            embeddings=None,
            use_jsonb=True,
        )

        metadatas = []
        for split in splits:
            meta = dict(split.metadata)
            meta.update({
                "user_id": str(doc.user.id),
                "document_id": str(doc.id),
                "file_name": doc.file_name
            })
            metadatas.append(meta)

        store.add_embeddings(
            texts=texts,
            embeddings=embeddings,
            metadatas=metadatas
        )
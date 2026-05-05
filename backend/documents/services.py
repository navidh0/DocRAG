from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, cast, Any
from uuid import UUID

import ollama

from django.db import connection, transaction
from django.db import ProgrammingError
from django.conf import settings

from langchain_postgres import PGVector
from langchain_community.document_loaders import PyMuPDFLoader, UnstructuredExcelLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document as LCDocument
from langchain_core.embeddings import Embeddings

from .models import Document
from .utils import get_vector_store_connection
from .exceptions import DocumentNotFoundError, DocumentProcessingError

if TYPE_CHECKING:
    from accounts.models import User

logger = logging.getLogger(__name__)


# =========================
# CREATE DOCUMENT
# =========================

class CreateDocumentService:
    @staticmethod
    def execute(*, user: User, validated_data: dict[str, Any]) -> Document:
        doc = Document.objects.create(user=user, **validated_data)
        logger.info("Document created: id=%s file_name=%s user=%s", doc.id, doc.file_name, user.id)

        from .tasks import process_document_embedding

        transaction.on_commit(
            lambda: process_document_embedding.delay(str(doc.id))  # type: ignore
        )

        return doc


# =========================
# DELETE DOCUMENT
# =========================

class DeleteDocumentService:
    @staticmethod
    def execute(*, user: User, document_id: UUID) -> dict[str, str]:
        try:
            doc = Document.objects.get(id=document_id, user=user)
        except Document.DoesNotExist:
            logger.warning("Delete failed — document not found: id=%s user=%s", document_id, user.id)
            raise DocumentNotFoundError("Document not found")

        data: dict[str, str] = {
            "id": str(doc.id),
            "file_name": doc.file_name,
        }

        doc.delete()
        logger.info("Document deleted: id=%s file_name=%s user=%s", document_id, data["file_name"], user.id)

        return data


# =========================
# DOCUMENT STATUS
# =========================

class GetDocumentStatusService:

    STATUS_DESCRIPTIONS: dict[str, str] = {
        "pending": "Waiting to be processed",
        "processing": "Extracting text and generating embeddings...",
        "completed": "Ready for Q&A",
        "failed": "Processing failed. Check file format or logs.",
    }

    @classmethod
    def execute(cls, *, user: User, document_id: UUID) -> dict[str, str]:
        try:
            doc = Document.objects.get(id=document_id, user=user)
        except Document.DoesNotExist:
            logger.warning("Status fetch failed — document not found: id=%s user=%s", document_id, user.id)
            raise DocumentNotFoundError("Document not found")

        return {
            "id": str(doc.id),
            "file_name": doc.file_name,
            "status": doc.status,
            "created_at": doc.created_at.isoformat(),
            "status_description": cls.STATUS_DESCRIPTIONS.get(doc.status, "Unknown"),
        }


# =========================
# DOCUMENT CHUNKS
# =========================

class DocumentChunksService:
    @staticmethod
    def execute(*, user: User, document_id: UUID) -> dict[str, Any]:
        sql = """
            SELECT cmetadata, document
            FROM langchain_pg_embedding
            WHERE cmetadata->>'document_id' = %s
              AND cmetadata->>'user_id' = %s
        """
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, [str(document_id), str(user.id)])
                rows: list[tuple[Any, Any]] = cursor.fetchall()
        except ProgrammingError as exc:
            if "langchain_pg_embedding" not in str(exc):
                logger.error(
                    "Unexpected DB error fetching chunks: id=%s user=%s",
                    document_id, user.id,
                    exc_info=True,
                )
                raise
            logger.warning(
                "langchain_pg_embedding table missing — returning empty chunks: id=%s", document_id
            )
            rows = []

        logger.info("Chunks fetched: id=%s total=%d user=%s", document_id, len(rows), user.id)

        return {
            "document_id": str(document_id),
            "total_chunks_found": len(rows),
            "chunks": [
                {
                    "content": (row[1] or "")[:150],
                    "metadata": row[0] if isinstance(row[0], dict) else json.loads(row[0]),
                }
                for row in rows
            ],
        }


# =========================
# PROCESS DOCUMENT (CORE)
# =========================

class ProcessDocumentService:

    @staticmethod
    def execute(document_id: UUID) -> None:
        logger.info("Processing started: id=%s", document_id)

        updated = Document.objects.filter(
            id=document_id,
            status="pending",
        ).update(status="processing")

        if updated == 0:
            logger.warning("Processing skipped — document not in pending state: id=%s", document_id)
            return

        doc = Document.objects.get(id=document_id)

        try:
            data = ProcessDocumentService._load_document(doc)
            splits = ProcessDocumentService._split_document(data)
            texts: list[str] = [split.page_content for split in splits]

            if not texts:
                raise DocumentProcessingError("Document contains no extractable text")

            embeddings = ProcessDocumentService._generate_embeddings(texts)
            ProcessDocumentService._store_embeddings(doc, splits, texts, embeddings)

            doc.status = "completed"
            logger.info("Processing completed: id=%s chunks=%d", document_id, len(texts))

        except DocumentProcessingError as exc:
            logger.warning(
                "Processing failed — expected error: id=%s reason=%s",
                document_id, exc.message,
            )
            doc.status = "failed"
            raise
        
        except Exception:
            logger.error(
                "Processing failed — unexpected error: id=%s",
                document_id,
                exc_info=True,
            )
            doc.status = "failed"
            raise
        
        finally:
            doc.save()

    # -------------------------
    # INTERNAL HELPERS
    # -------------------------

    @staticmethod
    def _load_document(doc: Document) -> list[LCDocument]:
        file_name = doc.file_name.lower()

        if file_name.endswith(".pdf"):
            loader = PyMuPDFLoader(doc.file.path)
            return loader.load()

        elif file_name.endswith((".xlsx", ".xls")):
            loader = UnstructuredExcelLoader(doc.file.path, mode="elements")
            return loader.load()

        elif file_name.endswith((".txt", ".csv")):
            with open(doc.file.path, "r", encoding="utf-8") as f:
                text = f.read()
            return [LCDocument(page_content=text, metadata={"source": doc.file_name})]

        raise DocumentProcessingError(f"Unsupported file type: {doc.file_name}")

    @staticmethod
    def _split_document(data: list[LCDocument]) -> list[LCDocument]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
        )
        return splitter.split_documents(data)

    @staticmethod
    def _generate_embeddings(texts: list[str]) -> list[list[float]]:
        client = ollama.Client(host=settings.OLLAMA_BASE_URL)
        response = client.embed(model=settings.OLLAMA_EMBED_MODEL, input=texts)
        return response["embeddings"]

    @staticmethod
    def _store_embeddings(
        doc: Document,
        splits: list[LCDocument],
        texts: list[str],
        embeddings: list[list[float]],
    ) -> None:
        conn = get_vector_store_connection()

        store = PGVector(
            collection_name="rag_collection",
            connection=conn,
            embeddings=cast(Embeddings, None),
            use_jsonb=True,
        )

        metadatas: list[dict[str, Any]] = []
        for split in splits:
            meta = dict(split.metadata)
            meta.update({
                "user_id": str(doc.user.id),
                "document_id": str(doc.id),
                "file_name": doc.file_name,
            })
            metadatas.append(meta)

        store.add_embeddings(texts=texts, embeddings=embeddings, metadatas=metadatas)
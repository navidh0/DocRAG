from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID
from celery import Task
from django.db import connection, transaction
from django.db import ProgrammingError

from documents.models import Document
from documents.selectors import document_get

if TYPE_CHECKING:
    from accounts.models import User

logger = logging.getLogger(__name__)


class CreateDocumentService:
    @staticmethod
    def execute(*, user: User, validated_data: dict[str, Any]) -> Document:
        doc = Document.objects.create(user=user, **validated_data)
        logger.info("Document created: id=%s file_name=%s user=%s", doc.id, doc.file_name, user.id)
        from documents.tasks import process_document_embedding #django circular import issue => i have tested the import at top

        transaction.on_commit(
            lambda: cast(Task, process_document_embedding).delay(str(doc.id)))
        return doc


class DeleteDocumentService:
    @staticmethod
    def execute(*, user: User, document_id: UUID) -> dict[str, str]:
        doc = document_get(user=user, document_id=document_id)
        data: dict[str, str] = {"id": str(doc.id), "file_name": doc.file_name}
        doc.delete()
        logger.info("Document deleted: id=%s file_name=%s user=%s", document_id, data["file_name"], user.id)
        return data


class GetDocumentStatusService:
    STATUS_DESCRIPTIONS: dict[str, str] = {
        Document.Status.PENDING: "Waiting to be processed",
        Document.Status.PROCESSING: "Extracting text and generating embeddings...",
        Document.Status.COMPLETED: "Ready for Q&A",
        Document.Status.FAILED: "Processing failed. Check file format or logs.",
    }

    @classmethod
    def execute(cls, *, user: User, document_id: UUID) -> dict[str, str]:
        doc = document_get(user=user, document_id=document_id)  
        return {
            "id": str(doc.id),
            "file_name": doc.file_name,
            "status": doc.status,
            "created_at": doc.created_at.isoformat(),
            "status_description": cls.STATUS_DESCRIPTIONS.get(doc.status, "Unknown"),
        }


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
                logger.error("Unexpected DB error fetching chunks: id=%s user=%s", document_id, user.id, exc_info=True)
                raise
            logger.warning("langchain_pg_embedding table missing — returning empty chunks: id=%s", document_id)
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
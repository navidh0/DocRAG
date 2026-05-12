from __future__ import annotations

import logging
from typing import Any, cast
from uuid import UUID

import ollama

from django.conf import settings

from langchain_postgres import PGVector
from langchain_community.document_loaders import PyMuPDFLoader, UnstructuredExcelLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document as LCDocument
from langchain_core.embeddings import Embeddings

from core.utils import get_vector_store_connection
from documents.models import Document
from documents.exceptions import DocumentProcessingError

logger = logging.getLogger(__name__)


class ProcessDocumentService:

    @staticmethod
    def execute(document_id: UUID) -> None:
        logger.info("Processing started: id=%s", document_id)

        updated = Document.objects.filter(id=document_id, status="pending").update(status="processing")
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
            logger.warning("Processing failed — expected error: id=%s reason=%s", document_id, exc.message)
            doc.status = "failed"
            raise

        except Exception:
            logger.error("Processing failed — unexpected error: id=%s", document_id, exc_info=True)
            doc.status = "failed"
            raise

        finally:
            doc.save()

    @staticmethod
    def _load_document(doc: Document) -> list[LCDocument]:
        file_name = doc.file_name.lower()

        if file_name.endswith(".pdf"):
            return PyMuPDFLoader(doc.file.path).load()
        elif file_name.endswith((".xlsx", ".xls")):
            return UnstructuredExcelLoader(doc.file.path, mode="elements").load()
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
        store = PGVector(
            collection_name="rag_collection",
            connection=get_vector_store_connection(),
            embeddings=cast(Embeddings, None),
            use_jsonb=True,
        )
        metadatas: list[dict[str, Any]] = []
        for i, split in enumerate(splits):
            meta = dict(split.metadata)
            meta.update({
                "user_id": str(doc.user.id),
                "document_id": str(doc.id),
                "file_name": doc.file_name,
                "chunk_index": i,
            })
            metadatas.append(meta)

        store.add_embeddings(texts=texts, embeddings=embeddings, metadatas=metadatas)
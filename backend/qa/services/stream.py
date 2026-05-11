from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING

from django.conf import settings

from documents.exceptions import DocumentNotFoundError
from documents.selectors import document_exists_for_user
from qa.exceptions import DocumentRetrievalError, EmbeddingGenerationError
from qa.models import QuestionActivity
from .activity import IncrementQuestionCountService
from .embedding import get_query_embedding
from .retrieval import retrieve_documents
from .reranking import BM25Reranker
from .streaming import (
    create_optimized_prompt, 
    extract_sources, 
    stream_response_buffered,
    check_ollama_connection,
)

if TYPE_CHECKING:
    from accounts.models import User

logger = logging.getLogger(__name__)


class StreamQuestionService:
    @staticmethod
    def execute(*, user: User, validated_data: dict):
        """
        Returns a generator of NDJSON strings for use with StreamingHttpResponse.

        Setup phase (embedding + retrieval) runs eagerly before the generator
        is entered, so failures surface as proper DRF error responses rather
        than mid-stream JSON error chunks.

        All side effects (QuestionActivity creation + count increment) are
        inside the generator and only execute on stream completion.
        """
        question = validated_data["question"]
        doc_id = validated_data.get("document_id")
        start_time = time.time()

        # -- Ownership check ---------------------------------------------------
        if doc_id is not None and not document_exists_for_user(doc_id=doc_id, user=user):
            raise DocumentNotFoundError(
                "Document not found or does not belong to you.",
                details={"document_id": str(doc_id)},
            )

        # -- Setup phase -------------------------------------------------------
        check_ollama_connection()
        
        try:
            query_vector = get_query_embedding(question)
        except Exception as exc:
            raise EmbeddingGenerationError(
                "Failed to generate question embedding for streaming.",
                details={"error": str(exc)},
            ) from exc

        try:
            docs = retrieve_documents(
                query_vector=query_vector,
                user_id=str(user.id),
                doc_id=str(doc_id) if doc_id else None,
                k=settings.TOP_K_CHUNKS,
            )
        except Exception as exc:
            raise DocumentRetrievalError(
                "Failed to retrieve documents for streaming.",
                details={"error": str(exc)},
            ) from exc

        # -- Generator ---------------------------------------------------------
        def _generator():
            if not docs:
                execution_time = int((time.time() - start_time) * 1000)
                QuestionActivity.objects.create(
                    user=user,
                    document_id=doc_id,
                    question=question,
                    answer="No relevant information found.",
                    sources=[],
                    response_time_ms=execution_time,
                    status="no_answer",
                )
                IncrementQuestionCountService.execute(user_id=str(user.id))
                yield json.dumps(
                    {"status": "no_answer", "answer": "No relevant information found."}
                ) + "\n"
                return

            doc_count = len({d.metadata.get("document_id") for d in docs})
            top_k = min(doc_count * settings.RERANK_TOP_K_PER_DOC, settings.RERANK_TOP_K_MAX)

            reranked_docs = BM25Reranker().rerank(
                question=question,
                documents=docs,
                top_k=top_k,
            )
            sources = extract_sources(reranked_docs)
            prompt = create_optimized_prompt(
                context="\n\n".join(d.page_content for d in reranked_docs),
                question=question,
            )

            # -- Stream tokens -------------------------------------------------
            full_response = ""
            try:
                for buffered_chunk in stream_response_buffered(prompt, buffer_size=3):
                    full_response += json.loads(buffered_chunk.strip()).get("token", "")
                    yield buffered_chunk
            except Exception as exc:
                logger.error("[StreamQuestionService] Mid-stream error: %s", exc)
                execution_time = int((time.time() - start_time) * 1000)
                QuestionActivity.objects.create(
                    user=user,
                    document_id=doc_id,
                    question=question,
                    answer="Stream interrupted.",
                    sources=sources,
                    response_time_ms=execution_time,
                    status="error",
                )
                IncrementQuestionCountService.execute(user_id=str(user.id))
                yield json.dumps({"status": "error", "error": "Stream interrupted."}) + "\n"
                return

            # -- Post-stream side effects --------------------------------------
            execution_time = int((time.time() - start_time) * 1000)
            QuestionActivity.objects.create(
                user=user,
                document_id=doc_id,
                question=question,
                answer=full_response,
                sources=sources,
                response_time_ms=execution_time,
                status="success",
            )
            IncrementQuestionCountService.execute(user_id=str(user.id))

        return _generator()
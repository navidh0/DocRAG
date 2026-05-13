from __future__ import annotations

import logging
import time

from django.conf import settings

from qa.exceptions import (
    DocumentRetrievalError,
    EmbeddingGenerationError,
)
from qa.models import QuestionActivity
from .activity import IncrementQuestionCountService, QuestionActivityCreateService
from .embedding import get_query_embedding
from .retrieval import retrieve_documents
from .reranking import HybridReranker
from .streaming import create_optimized_prompt, extract_sources

import ollama

logger = logging.getLogger(__name__)


class ProcessQuestionService:
    @staticmethod
    def execute(
        *,
        question: str,
        user_id: str,
        doc_id: str | None,
        page_filter: int | None,
        task_id: str | None = None,
    ) -> dict:
        start_time = time.time()

        # -- Step 1: Embedding (Redis-cached) ----------------------------------
        try:
            query_vector = get_query_embedding(question)
        except Exception as exc:
            raise EmbeddingGenerationError(
                "Failed to generate question embedding.",
                details={"error": str(exc)},
            ) from exc

        # -- Step 2: Retrieval -------------------------------------------------
        try:
            docs = retrieve_documents(
                query_vector=query_vector,
                user_id=user_id,
                doc_id=doc_id,
                k=settings.TOP_K_CHUNKS,
                page_filter=page_filter,
            )
        except Exception as exc:
            raise DocumentRetrievalError(
                "Failed to retrieve documents from vector store.",
                details={"error": str(exc)},
            ) from exc

        execution_time = int((time.time() - start_time) * 1000)

        # -- Step 3: No results ------------------------------------------------
        if not docs:
            QuestionActivityCreateService.execute(
                user_id=user_id,
                doc_id=doc_id,
                question=question,
                answer="I could not find relevant information in the provided documents.",
                sources=[],
                response_time_ms=execution_time,
                status="no_answer",
                task_id=task_id,
            )
            IncrementQuestionCountService.execute(user_id=user_id)
            return {
                "status": "no_answer",
                "answer": "I could not find relevant information in the provided documents.",
                "sources": [],
                "response_time_ms": execution_time,
            }

        # -- Step 4: Hybrid rerank ---------------------------------------------
        doc_count = len({d.metadata.get("document_id") for d in docs})
        top_k = min(doc_count * settings.RERANK_TOP_K_PER_DOC, settings.RERANK_TOP_K_MAX)

        try:
            reranked_docs = HybridReranker(top_k=top_k).rerank(
                question=question,
                documents=docs,
            )
        except Exception as exc:
            logger.warning(
                "[ProcessQuestionService] Reranking failed, falling back to top-%d. Error: %s",
                top_k,
                exc,
            )
            reranked_docs = docs[:top_k]

        # -- Step 5: Build prompt ----------------------------------------------
        context_parts = []
        for doc in reranked_docs:
            meta = doc.metadata
            display_page = meta.get("page", 0) + 1  # DB is 0-based, prompt is 1-based
            context_parts.append(
                f"[Document: {meta.get('file_name', 'Unknown')} | Page: {display_page}]\n"
                f"{doc.page_content}"
            )
        prompt = create_optimized_prompt(
            context="\n\n".join(context_parts),
            question=question,
        )

        # -- Step 6: Generate answer -------------------------------------------
        try:
            client = ollama.Client(host=settings.OLLAMA_BASE_URL)
            answer = client.generate(
                model=settings.OLLAMA_CHAT_MODEL,
                prompt=prompt,
                stream=False,
            )["response"].strip()
        except Exception as exc:
            execution_time = int((time.time() - start_time) * 1000)
            QuestionActivityCreateService.execute(
                user_id=user_id,
                doc_id=doc_id,
                question=question,
                answer="An error occurred during answer generation.",
                sources=[],
                response_time_ms=execution_time,
                status="error",
                task_id=task_id,
            )
            logger.error(
                "[ProcessQuestionService] Ollama generation failed. user_id=%s error=%s",
                user_id,
                exc,
            )
            return {
                "status": "error",
                "answer": "An error occurred during answer generation.",
                "sources": [],
                "response_time_ms": execution_time,
            }

        # -- Step 7: Sources, persist, increment -------------------------------
        sources = extract_sources(reranked_docs)
        execution_time = int((time.time() - start_time) * 1000)

        QuestionActivity.objects.create(
            user_id=user_id,
            document_id=doc_id,
            question=question,
            answer=answer,
            sources=sources,
            response_time_ms=execution_time,
            status="success",
            task_id=task_id
        )
        IncrementQuestionCountService.execute(user_id=user_id)

        return {
            "status": "success",
            "answer": answer,
            "sources": sources,
            "response_time_ms": execution_time,
        }
# qa/services.py
from __future__ import annotations

import json
import logging
import time

import ollama
from django.conf import settings
from django.db.models import F
from langchain_postgres import PGVector

from documents.utils import get_vector_store_connection

from .exceptions import (
    DocumentRetrievalError,
    EmbeddingGenerationError,
    QAServiceError,
)
from .models import QuestionActivity
from .reranking import BM25Reranker, HybridReranker
from .streaming import StreamOptimizer, create_optimized_prompt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal utility service
# ---------------------------------------------------------------------------

class IncrementQuestionCountService:
    @staticmethod
    def execute(*, user_id: str) -> None:
        from django.contrib.auth import get_user_model

        get_user_model().objects.filter(id=user_id).update(
            question_count=F("question_count") + 1
        )


# ---------------------------------------------------------------------------
# ProcessQuestionService — full RAG pipeline, called by Celery task
# ---------------------------------------------------------------------------

class ProcessQuestionService:
    @staticmethod
    def execute(
        *,
        question: str,
        user_id: str,
        doc_id: str | None,
        page_filter: int | None,
    ) -> dict:
        start_time = time.time()

        # -- Step 1: Generate embedding ----------------------------------------
        try:
            client = ollama.Client(host=settings.OLLAMA_BASE_URL)
            embed_response = client.embed(
                model=settings.OLLAMA_EMBED_MODEL,
                input=question,
            )
            query_vector = embed_response["embeddings"][0]
        except Exception as exc:
            raise EmbeddingGenerationError(
                "Failed to generate question embedding.",
                details={"error": str(exc)},
            ) from exc

        # -- Step 2: Retrieve documents from PGVector --------------------------
        try:
            connection = get_vector_store_connection()
            store = PGVector(
                collection_name="rag_collection",
                connection=connection,
                embeddings=None,
                use_jsonb=True,
            )
            search_filter = {"user_id": str(user_id)}
            if doc_id:
                search_filter["document_id"] = str(doc_id)
            if page_filter is not None:
                # API accepts 1-based; DB stores 0-based
                search_filter["page"] = int(page_filter) - 1

            docs = store.similarity_search_by_vector(
                embedding=query_vector,
                k=settings.TOP_K_CHUNKS,
                filter=search_filter,
            )
        except Exception as exc:
            raise DocumentRetrievalError(
                "Failed to retrieve documents from vector store.",
                details={"error": str(exc)},
            ) from exc

        execution_time = int((time.time() - start_time) * 1000)

        # -- Step 3: No results ------------------------------------------------
        if not docs:
            QuestionActivity.objects.create(
                user_id=user_id,
                document_id=doc_id,
                question=question,
                answer="I could not find relevant information in the provided documents.",
                sources=[],
                response_time_ms=execution_time,
                status="no_answer",
            )
            IncrementQuestionCountService.execute(user_id=user_id)
            return {
                "status": "no_answer",
                "answer": "I could not find relevant information in the provided documents.",
                "sources": [],
                "response_time_ms": execution_time,
            }

        # -- Step 4: Hybrid rerank ---------------------------------------------
        try:
            reranked_docs = HybridReranker().rerank(question=question, documents=docs)
        except Exception as exc:
            logger.warning(
                "[ProcessQuestionService] Reranking failed, falling back to top-%d. Error: %s",
                settings.RERANK_TOP_K,
                exc,
            )
            reranked_docs = docs[: settings.RERANK_TOP_K]

        # -- Step 5: Build prompt ----------------------------------------------
        context_parts = []
        for doc in reranked_docs:
            meta = doc.metadata
            # Page stored 0-based in DB — display 1-based in prompt for LLM
            display_page = meta.get("page", 0) + 1
            context_parts.append(
                f"[Document: {meta.get('file_name', 'Unknown')} | Page: {display_page}]\n"
                f"{doc.page_content}"
            )
        context = "\n\n".join(context_parts)
        prompt = create_optimized_prompt(context=context, question=question)

        # -- Step 6: Generate answer -------------------------------------------
        try:
            gen_response = client.generate(
                model=settings.OLLAMA_CHAT_MODEL,
                prompt=prompt,
                stream=False,
            )
            answer = gen_response["response"].strip()
        except Exception as exc:
            execution_time = int((time.time() - start_time) * 1000)
            QuestionActivity.objects.create(
                user_id=user_id,
                document_id=doc_id,
                question=question,
                answer="An error occurred during answer generation.",
                sources=[],
                response_time_ms=execution_time,
                status="error",
            )
            raise QAServiceError(
                "Failed to generate answer.",
                status_code=503,
                details={"error": str(exc)},
            ) from exc

        # -- Step 7: Build sources (convert page back to 1-based) --------------
        sources = []
        for doc in reranked_docs:
            meta = doc.metadata
            excerpt = doc.page_content
            sources.append({
                "file_name": meta.get("file_name", "Unknown"),
                "page": meta.get("page", 0) + 1,
                "chunk_index": meta.get("chunk_index", 0),
                "excerpt": (excerpt[:200] + "...") if len(excerpt) > 200 else excerpt,
            })

        execution_time = int((time.time() - start_time) * 1000)

        # -- Step 8: Persist activity ------------------------------------------
        QuestionActivity.objects.create(
            user_id=user_id,
            document_id=doc_id,
            question=question,
            answer=answer,
            sources=sources,
            response_time_ms=execution_time,
            status="success",
        )

        # -- Step 9: Increment count -------------------------------------------
        IncrementQuestionCountService.execute(user_id=user_id)

        return {
            "status": "success",
            "answer": answer,
            "sources": sources,
            "response_time_ms": execution_time,
        }


# ---------------------------------------------------------------------------
# AskQuestionService — submits Celery task, returns task_id immediately
# ---------------------------------------------------------------------------

class AskQuestionService:
    @staticmethod
    def execute(*, user, validated_data: dict) -> dict:
        from .tasks import process_question_task

        doc_id = validated_data.get("document_id")
        task = process_question_task.delay(
            question=validated_data["question"],
            user_id=str(user.id),
            doc_id=str(doc_id) if doc_id else None,
            page_filter=validated_data.get("page"),
        )
        return {"task_id": str(task.id), "status": "processing"}


# ---------------------------------------------------------------------------
# GetQuestionResultService — polls Celery result backend
# ---------------------------------------------------------------------------

class GetQuestionResultService:
    @staticmethod
    def execute(*, task_id: str) -> dict:
        from celery.result import AsyncResult

        result = AsyncResult(task_id)

        if result.state in ("PENDING", "STARTED"):
            return {"task_id": task_id, "status": "processing"}

        if result.state == "SUCCESS":
            return {"task_id": task_id, **result.result}

        if result.state == "FAILURE":
            raise QAServiceError(
                "Question processing failed.",
                status_code=500,
                details={"error": str(result.result)},
            )

        # REVOKED or unknown state
        raise QAServiceError(
            f"Unexpected task state: {result.state}",
            status_code=500,
            details={"task_id": task_id, "state": result.state},
        )


# ---------------------------------------------------------------------------
# StreamQuestionService — returns a generator, view wraps in StreamingHttpResponse
# ---------------------------------------------------------------------------

class StreamQuestionService:
    @staticmethod
    def execute(*, user, validated_data: dict):
        """
        Returns a generator of NDJSON strings.
        All side effects (QuestionActivity creation, count increment) happen
        inside the generator so they are tied to actual stream completion,
        not just stream setup.
        """
        question = validated_data["question"]
        doc_id = validated_data.get("document_id")
        start_time = time.time()

        optimizer = StreamOptimizer()

        # -- Embedding (setup phase — failure raises before generator is entered) --
        try:
            query_vector = optimizer.get_query_embedding(question)
        except Exception as exc:
            raise EmbeddingGenerationError(
                "Failed to generate question embedding for streaming.",
                details={"error": str(exc)},
            ) from exc

        # -- Retrieval (setup phase) -------------------------------------------
        try:
            docs = optimizer.retrieve_documents(
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

        def _generator():
            nonlocal docs

            # -- No results ----------------------------------------------------
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
                yield json.dumps({
                    "status": "no_answer",
                    "answer": "No relevant information found.",
                }) + "\n"
                return

            # -- BM25 rerank only (no LLM call — latency is priority) ----------
            reranked_docs = BM25Reranker().rerank(
                question=question,
                documents=docs,
                top_k=settings.RERANK_TOP_K,
            )

            sources = optimizer.extract_sources(reranked_docs)
            context = "\n\n".join([d.page_content for d in reranked_docs])
            prompt = create_optimized_prompt(context=context, question=question)

            # -- Stream tokens -------------------------------------------------
            full_response = ""
            try:
                for buffered_chunk in optimizer.stream_response_buffered(
                    prompt, buffer_size=3
                ):
                    chunk_data = json.loads(buffered_chunk.strip())
                    full_response += chunk_data.get("token", "")
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
                yield json.dumps({
                    "error": "Stream interrupted.",
                    "status": "error",
                }) + "\n"
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
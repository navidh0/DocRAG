from __future__ import annotations
from typing import TYPE_CHECKING, Any, cast

import json
import logging
import time

import ollama
from django.conf import settings
from django.db.models import F
from langchain_postgres import PGVector
from celery.result import AsyncResult
from django.contrib.auth import get_user_model

from  core.utils import get_vector_store_connection
from documents.models import Document 
from documents.exceptions import DocumentNotFoundError

from .exceptions import (
    DocumentRetrievalError,
    EmbeddingGenerationError,
    QAServiceError,
    QuestionActivityNotFoundError
)
from .selectors import (                 
    question_activity_list,
    QuestionActivityListFilters,
)
from .models import QuestionActivity
from .reranking import BM25Reranker, HybridReranker
from .streaming import StreamOptimizer, create_optimized_prompt

if TYPE_CHECKING:
    from accounts.models import User

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal utility service
# ---------------------------------------------------------------------------

class IncrementQuestionCountService:
    @staticmethod
    def execute(*, user_id: str) -> None:

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
                embeddings=None,  # type: ignore[arg-type]
                use_jsonb=True,
            )

            if doc_id:
                # Scoped query — single document, original behaviour preserved
                search_filter: dict = {"user_id": str(user_id)}
                search_filter["document_id"] = str(doc_id)
                if page_filter is not None:
                    # API accepts 1-based; DB stores 0-based
                    search_filter["page"] = int(page_filter) - 1

                docs = store.similarity_search_by_vector(
                    embedding=query_vector,
                    k=settings.TOP_K_CHUNKS,
                    filter=search_filter,
                )
            else:
                # Global query — fetch per document to guarantee representation
                user_doc_ids = list(
                    Document.objects.filter(user_id=user_id, status="completed")
                    .values_list("id", flat=True)
                )
                docs = []
                for d_id in user_doc_ids:
                    per_doc_chunks = store.similarity_search_by_vector(
                        embedding=query_vector,
                        k=settings.TOP_K_CHUNKS_PER_DOC,
                        filter={
                            "user_id": str(user_id),
                            "document_id": str(d_id),
                        },
                    )
                    docs.extend(per_doc_chunks)

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
        doc_count = len({d.metadata.get("document_id") for d in docs})
        top_k = min(doc_count * settings.RERANK_TOP_K_PER_DOC, settings.RERANK_TOP_K_MAX)

        try:
            reranked_docs = HybridReranker(top_k=top_k).rerank(question=question, documents=docs)
        except Exception as exc:
            logger.warning(
                "[ProcessQuestionService] Reranking failed, falling back to top-%d. "
                "Error: %s",
                top_k,
                exc,
            )
            reranked_docs = docs[:top_k]

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
            sources.append(
                {
                    "file_name": meta.get("file_name", "Unknown"),
                    "page": meta.get("page", 0) + 1,
                    "chunk_index": meta.get("chunk_index", 0),
                    "excerpt": (excerpt[:200] + "...") if len(excerpt) > 200 else excerpt,
                }
            )

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
        from .tasks import process_question_task #django circular import => tasks calls the method

        doc_id = validated_data.get("document_id")
        
        if doc_id is not None:
            if not Document.objects.filter(id=doc_id, user=user).exists():
                raise DocumentNotFoundError(
                    "Document not found or does not belong to you.",
                    details={"document_id": str(doc_id)},
                )

        celery_task: Any = process_question_task  # Celery decorates .delay() at runtime => pylance issue
        task = celery_task.delay(
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
# StreamQuestionService — returns a generator for StreamingHttpResponse
# ---------------------------------------------------------------------------


class StreamQuestionService:
    @staticmethod
    def execute(*, user, validated_data: dict):
        """
        Returns a generator of NDJSON strings.
        Embedding and retrieval errors are raised in the setup phase (before
        the generator is entered) so they surface as proper DRF error responses
        via custom_exception_handler, not as mid-stream JSON error chunks.
        All side effects (QuestionActivity + count increment) are inside the
        generator so they are tied to actual stream completion.
        """
        question = validated_data["question"]
        doc_id = validated_data.get("document_id")
        start_time = time.time()

        optimizer = StreamOptimizer()
        
        if doc_id is not None:
            if not Document.objects.filter(id=doc_id, user=user).exists():
                raise DocumentNotFoundError(
                    "Document not found or does not belong to you.",
                    details={"document_id": str(doc_id)},
                )

        # -- Setup phase: failures raise before the generator is entered -------

        try:
            query_vector = optimizer.get_query_embedding(question)
        except Exception as exc:
            raise EmbeddingGenerationError(
                "Failed to generate question embedding for streaming.",
                details={"error": str(exc)},
            ) from exc

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

        # -- Generator: all streaming logic and side effects are here ----------

        def _generator():
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
                yield json.dumps(
                    {
                        "status": "no_answer",
                        "answer": "No relevant information found.",
                    }
                ) + "\n"
                return

            doc_count = len({d.metadata.get("document_id") for d in docs})
            top_k = min(doc_count * settings.RERANK_TOP_K_PER_DOC, settings.RERANK_TOP_K_MAX)

            reranked_docs = BM25Reranker().rerank(
                question=question,
                documents=docs,
                top_k=top_k,
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
                yield json.dumps(
                    {"error": "Stream interrupted.", "status": "error"}
                ) + "\n"
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
    
# ---------------------------------------------------------------------------
# QuestionActivityListService — validates document ownership and returns
# filtered QuestionActivity records for the given user
# ---------------------------------------------------------------------------

class QuestionActivityListService:
    @staticmethod
    def execute(*, user: User, filters: QuestionActivityListFilters | None = None):
        raw: dict[str, Any] = cast(dict[str, Any], filters) if filters else {}
        doc_id = raw.get("document_id")

        if doc_id:
            if not Document.objects.filter(id=doc_id, user=user).exists():
                raise QuestionActivityNotFoundError(
                    "Document not found or does not belong to you.",
                    details={"document_id": str(doc_id)},
                )

        return question_activity_list(user=user, filters=filters)
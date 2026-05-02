from __future__ import annotations

import hashlib
import json
import logging

import ollama
import redis
from django.conf import settings
from langchain_postgres import PGVector

from documents.utils import get_vector_store_connection

logger = logging.getLogger(__name__)


class StreamOptimizer:
    def __init__(self) -> None:
        self.client = ollama.Client(host=settings.OLLAMA_BASE_URL)
        self.embedding_model = settings.OLLAMA_EMBED_MODEL
        self.llm_model = settings.OLLAMA_CHAT_MODEL
        self.redis_client = self._get_redis_client()

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------

    def _get_redis_client(self):
        try:
            return redis.from_url(
                settings.CELERY_BROKER_URL,
                decode_responses=True,
            )
        except Exception as exc:
            logger.warning(
                "[StreamOptimizer] Redis client init failed, "
                "embedding cache disabled. Error: %s",
                exc,
            )
            return None

    @staticmethod
    def _embedding_cache_key(text: str) -> str:
        return f"embedding:{hashlib.md5(text.encode()).hexdigest()}"

    # ------------------------------------------------------------------
    # Embedding with Redis cache
    # ------------------------------------------------------------------

    def get_query_embedding(self, question: str) -> list[float]:
        cache_key = self._embedding_cache_key(question)

        if self.redis_client:
            try:
                cached = self.redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception as exc:
                logger.warning("[StreamOptimizer] Redis read failed: %s", exc)

        response = self.client.embed(
            model=self.embedding_model,
            input=question,
        )
        embedding = response["embeddings"][0]

        if self.redis_client:
            try:
                self.redis_client.setex(
                    cache_key,
                    86400,
                    json.dumps(embedding),
                )
            except Exception as exc:
                logger.warning("[StreamOptimizer] Redis write failed: %s", exc)

        return embedding

    # ------------------------------------------------------------------
    # Document retrieval
    # ------------------------------------------------------------------

    def retrieve_documents(
        self,
        *,
        query_vector: list[float],
        user_id: str,
        doc_id: str | None = None,
        k: int,
    ) -> list:
        connection = get_vector_store_connection()
        store = PGVector(
            collection_name="rag_collection",
            connection=connection,
            embeddings=None,
            use_jsonb=True,
        )
        search_filter: dict = {"user_id": str(user_id)}
        if doc_id:
            search_filter["document_id"] = str(doc_id)

        return store.similarity_search_by_vector(
            embedding=query_vector,
            k=k,
            filter=search_filter,
        )

    # ------------------------------------------------------------------
    # Buffered streaming
    # ------------------------------------------------------------------

    def stream_response_buffered(self, prompt: str, buffer_size: int = 3):
        """
        Yields NDJSON lines: {"token": "<text>"}.
        Buffers `buffer_size` tokens before yielding to reduce
        the number of HTTP chunks sent to the client.
        """
        buffer: list[str] = []
        for chunk in self.client.generate(
            model=self.llm_model,
            prompt=prompt,
            stream=True,
        ):
            token = chunk.get("response", "")
            if token:
                buffer.append(token)
                if len(buffer) >= buffer_size:
                    yield json.dumps({"token": "".join(buffer)}) + "\n"
                    buffer = []

        if buffer:
            yield json.dumps({"token": "".join(buffer)}) + "\n"

    # ------------------------------------------------------------------
    # Source extraction
    # ------------------------------------------------------------------

    def extract_sources(self, docs: list) -> list[dict]:
        sources = []
        for doc in docs:
            meta = doc.metadata
            excerpt = doc.page_content
            sources.append(
                {
                    "file_name": meta.get("file_name", "Unknown"),
                    # Page stored 0-based in DB — always surface 1-based to callers
                    "page": meta.get("page", 0) + 1,
                    "chunk_index": meta.get("chunk_index", 0),
                    "excerpt": (excerpt[:200] + "...") if len(excerpt) > 200 else excerpt,
                }
            )
        return sources


# ---------------------------------------------------------------------------
# Module-level prompt builder — no class state needed
# ---------------------------------------------------------------------------


def create_optimized_prompt(*, context: str, question: str) -> str:
    return (
        "Context:\n"
        f"{context}\n\n"
        "Question:\n"
        f"{question}\n\n"
        "Answer Instructions:\n"
        "- Base your answer ONLY on the provided context\n"
        "- Be concise and direct\n"
        "- If the context doesn't contain relevant information, say so\n\n"
        "Answer:"
    )
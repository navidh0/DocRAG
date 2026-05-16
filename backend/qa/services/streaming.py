from __future__ import annotations

import json
import logging

import ollama
from django.conf import settings
from qa.exceptions import OllamaUnavailableError

logger = logging.getLogger(__name__)


def stream_response_buffered(prompt: str, buffer_size: int = 3):
    """
    Yields NDJSON lines: {"token": "<text>"}.
    Buffers `buffer_size` tokens before yielding to reduce
    the number of HTTP chunks sent to the client.
    """
    client = ollama.Client(host=settings.OLLAMA_BASE_URL, timeout=settings.OLLAMA_TIMEOUT)
    buffer: list[str] = []

    for chunk in client.generate(
        model=settings.OLLAMA_CHAT_MODEL,
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


def extract_sources(docs: list) -> list[dict]:
    sources = []
    for doc in docs:
        meta = doc.metadata
        excerpt = doc.page_content
        sources.append(
            {
                "file_name": meta.get("file_name", "Unknown"),
                "page": meta.get("page", 0) + 1,  # DB is 0-based, callers expect 1-based
                "chunk_index": meta.get("chunk_index", 0),
                "excerpt": (excerpt[:200] + "...") if len(excerpt) > 200 else excerpt,
            }
        )
    return sources


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
    
def check_ollama_connection() -> None:
    """
    Lightweight preflight check — raises if Ollama is unreachable.
    Call this in the setup phase of any streaming service so the error
    surfaces as a proper HTTP response before headers are committed.
    """
    try:
        ollama.Client(host=settings.OLLAMA_BASE_URL).list()
    except Exception as exc:
        raise OllamaUnavailableError(
            "Ollama service is unreachable. Ensure Ollama is running.",
            details={"error": str(exc)},
        ) from exc
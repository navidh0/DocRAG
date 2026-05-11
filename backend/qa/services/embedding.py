from __future__ import annotations

import hashlib
import json
import logging

import ollama
import redis
from django.conf import settings

logger = logging.getLogger(__name__)


def _get_redis_client():
    try:
        return redis.from_url(settings.CELERY_BROKER_URL, decode_responses=True)
    except Exception as exc:
        logger.warning("[embedding] Redis init failed, cache disabled. Error: %s", exc)
        return None


def _cache_key(text: str) -> str:
    return f"embedding:{hashlib.md5(text.encode()).hexdigest()}"


def get_query_embedding(question: str) -> list[float]:
    """
    Returns the embedding vector for `question`.
    Checks Redis first; falls back to Ollama on miss or cache failure.
    TTL: 24 h.

    Note: cache key does not include the model name. If OLLAMA_EMBED_MODEL
    changes, flush the embedding:* keyspace manually or wait for TTL expiry.
    """
    redis_client = _get_redis_client()
    cache_key = _cache_key(question)

    if redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as exc:
            logger.warning("[embedding] Redis read failed: %s", exc)

    client = ollama.Client(host=settings.OLLAMA_BASE_URL)
    embedding = client.embed(
        model=settings.OLLAMA_EMBED_MODEL,
        input=question,
    )["embeddings"][0]

    if redis_client:
        try:
            redis_client.setex(cache_key, 86400, json.dumps(embedding))
        except Exception as exc:
            logger.warning("[embedding] Redis write failed: %s", exc)

    return embedding
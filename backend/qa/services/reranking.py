from __future__ import annotations

import json
import logging
import re

import ollama
from django.conf import settings
from rank_bm25 import BM25Okapi

from qa.exceptions import RerankingError, OllamaUnavailableError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize_scores(scores: list[float]) -> list[float]:
    """
    Linearly scales scores to [0, 1].
    Returns uniform weights if all scores are identical (including all-zero)
    so downstream blending remains valid.
    """
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return [1.0 / len(scores)] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]


def _parse_llm_scores(raw: str, expected_count: int) -> list[float]:
    """
    Robustly extracts a scores list from an LLM response that may:
    - be wrapped in ```json ... ``` fences
    - have leading/trailing whitespace or preamble text
    - be empty (raises ValueError so callers can degrade gracefully)
    """
    if not raw or not raw.strip():
        raise ValueError("LLM returned an empty response")

    cleaned = re.sub(r"```(?:json)?", "", raw).strip()

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)

    data = json.loads(cleaned)
    scores = data.get("scores", [])

    if len(scores) < expected_count:
        scores += [0] * (expected_count - len(scores))
    return [float(s) for s in scores[:expected_count]]


# ---------------------------------------------------------------------------
# BM25Reranker
# ---------------------------------------------------------------------------

class BM25Reranker:
    """
    Lexical reranker using BM25Okapi.
    No network calls — safe to use in the streaming path.

    score() returns raw scores for all documents (used by HybridReranker).
    rerank() returns the top-k documents sorted by score.
    """

    def score(self, question: str, documents: list) -> list[float]:
        tokenized_corpus = [doc.page_content.split() for doc in documents]
        return BM25Okapi(tokenized_corpus).get_scores(question.split()).tolist()

    def rerank(self, question: str, documents: list, top_k: int) -> list:
        if not documents:
            return []
        try:
            scores = self.score(question, documents)
            ranked = sorted(zip(scores, documents), key=lambda p: p[0], reverse=True)
            return [doc for _, doc in ranked[:top_k]]
        except Exception as exc:
            logger.warning(
                "[BM25Reranker] Reranking failed, falling back to original order. Error: %s",
                exc,
            )
            return documents[:top_k]


# ---------------------------------------------------------------------------
# LLMReranker
# ---------------------------------------------------------------------------

class LLMReranker:
    """
    Semantic reranker backed by the Ollama chat model.
    Used only in the Celery path (HybridReranker) — never in streaming.

    score() returns raw LLM relevance scores for all documents (used by HybridReranker).
    rerank() returns the top-k documents sorted by score.
    Raises RerankingError on connection failure so the caller can decide
    whether to degrade or propagate.
    """

    def __init__(self) -> None:
        self.client = ollama.Client(host=settings.OLLAMA_BASE_URL)
        self.model = settings.OLLAMA_CHAT_MODEL

    @staticmethod
    def build_prompt(question: str, documents: list) -> str:
        prompt = (
            "You are a relevance scoring expert.\n"
            "Score each document's relevance to the question on a scale of 0–100.\n\n"
            f"Question: {question}\n\n"
            "Documents:\n"
        )
        for i, doc in enumerate(documents):
            prompt += f"\n[{i}] {doc.page_content[:300]}"
        prompt += (
            '\n\nProvide scores as JSON only: {"scores": [85, 70, 45, ...]}\n'
            "One integer per document, same order. No other text."
        )
        return prompt

    def score(self, question: str, documents: list) -> list[float]:
        """
        Returns raw LLM relevance scores without top-k filtering.
        Raises RerankingError on Ollama connection failure.
        Falls back to zeros on parse failure so HybridReranker can degrade gracefully.
        """
        try:
            response = self.client.generate(
                model=self.model,
                prompt=self.build_prompt(question, documents),
                format="json",
                stream=False,
            )
        except Exception as exc:
            raise OllamaUnavailableError(  # connection failure — hard stop
                "Ollama service is unreachable during reranking.",
                details={"error": str(exc)},
            ) from exc
            
        try:
            return _parse_llm_scores(response["response"], len(documents))
        except Exception as exc:
            logger.warning(
                "[LLMReranker] Could not parse scores, returning zeros. Raw: %r. Error: %s",
                response.get("response", ""),
                exc,
            )
            return [0.0] * len(documents)

    def rerank(self, question: str, documents: list, top_k: int) -> list:
        if not documents:
            return []
        scores = self.score(question, documents)
        ranked = sorted(enumerate(documents), key=lambda p: scores[p[0]], reverse=True)
        return [doc for _, doc in ranked[:top_k]]


# ---------------------------------------------------------------------------
# HybridReranker
# ---------------------------------------------------------------------------

class HybridReranker:
    """
    Blends BM25 (lexical) and LLM (semantic) scores using configurable weights.
    All weights and top_k come from settings — no hardcoded values.

    Used only in the Celery task path (ProcessQuestionService).
    The streaming path uses BM25Reranker directly (no LLM round-trip).
    """

    def __init__(self, top_k: int) -> None:
        self.top_k = top_k
        self.bm25_weight: float = settings.RERANK_BM25_WEIGHT
        self.llm_weight: float = settings.RERANK_LLM_WEIGHT
        self.bm25 = BM25Reranker()
        self.llm = LLMReranker()

    def rerank(self, question: str, documents: list) -> list:
        if not documents:
            return []

        try:
            raw_bm25 = self.bm25.score(question, documents)
        except Exception as exc:
            logger.warning("[HybridReranker] BM25 scoring failed: %s", exc)
            raw_bm25 = [0.0] * len(documents)

        try:
            raw_llm = self.llm.score(question, documents)
        except RerankingError:
            raise
        except Exception as exc:
            logger.warning(
                "[HybridReranker] LLM scoring failed, using BM25 only. Error: %s", exc
            )
            raw_llm = [0.0] * len(documents)

        norm_bm25 = _normalize_scores(raw_bm25)
        norm_llm = _normalize_scores(raw_llm)

        blended = [
            self.bm25_weight * b + self.llm_weight * l
            for b, l in zip(norm_bm25, norm_llm)
        ]

        ranked = sorted(zip(blended, documents), key=lambda p: p[0], reverse=True)
        return [doc for _, doc in ranked[:self.top_k]]
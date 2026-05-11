
from __future__ import annotations

import json
import logging
import re

import ollama
from django.conf import settings
from rank_bm25 import BM25Okapi

from .exceptions import RerankingError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_scores(scores: list[float]) -> list[float]:
    """
    Linearly scales a list of floats to [0, 1].
    If all scores are identical (including all-zero), returns uniform weights
    so downstream blending is still valid.
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
    - be empty (returns zeros so callers can degrade gracefully)
    """
    if not raw or not raw.strip():
        raise ValueError("LLM returned an empty response")

    # Strip markdown fences if present
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()

    # If there's preamble text, try to find the JSON object inside
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        cleaned = match.group(0)

    data = json.loads(cleaned)  # raises JSONDecodeError if still unparseable
    scores = data.get("scores", [])

    # Pad or trim to match document count
    if len(scores) < expected_count:
        scores += [0] * (expected_count - len(scores))
    scores = [float(s) for s in scores[:expected_count]]
    return scores


# ---------------------------------------------------------------------------
# BM25Reranker
# ---------------------------------------------------------------------------

class BM25Reranker:
    """
    Lexical reranker using BM25Okapi.
    No network calls — safe to use in the streaming path.
    """

    def rerank(self, question: str, documents: list, top_k: int) -> list:
        if not documents:
            return []
        try:
            tokenized_corpus = [doc.page_content.split() for doc in documents]
            bm25 = BM25Okapi(tokenized_corpus)
            query_tokens = question.split()
            scores = bm25.get_scores(query_tokens).tolist()
            ranked = sorted(
                zip(scores, documents),
                key=lambda pair: pair[0],
                reverse=True,
            )
            return [doc for _, doc in ranked[:top_k]]
        except Exception as exc:
            logger.warning(
                "[BM25Reranker] Reranking failed, falling back to original order. "
                "Error: %s",
                exc,
            )
            return documents[:top_k]


# ---------------------------------------------------------------------------
# LLMReranker
# ---------------------------------------------------------------------------

class LLMReranker:
    """
    Semantic reranker backed by the Ollama chat model.
    Used only in the async (Celery) path — never in streaming.
    Raises RerankingError on connection failure so the caller can decide
    whether to degrade or propagate.
    """

    def __init__(self) -> None:
        self.client = ollama.Client(host=settings.OLLAMA_BASE_URL)
        self.model = settings.OLLAMA_CHAT_MODEL

    def rerank(self, question: str, documents: list, top_k: int) -> list:
        if not documents:
            return []

        scoring_prompt = self._build_prompt(question, documents)

        try:
            response = self.client.generate(
                model=self.model,
                prompt=scoring_prompt,
                format="json",   # fix: forces Ollama to return valid JSON
                stream=False,
            )
        except Exception as exc:
            raise RerankingError(
                "LLM reranker could not reach Ollama.",
                details={"error": str(exc)},
            ) from exc

        try:
            raw = response["response"]
            scores = _parse_llm_scores(raw, len(documents))  # fix: robust parser
        except Exception as exc:
            logger.warning(
                "[LLMReranker] Could not parse scores, falling back to original order. "
                "Raw: %r. Error: %s",
                response.get("response", ""),
                exc,
            )
            return documents[:top_k]

        ranked = sorted(
            enumerate(documents),
            key=lambda pair: scores[pair[0]],
            reverse=True,
        )
        return [doc for _, doc in ranked[:top_k]]

    @staticmethod
    def _build_prompt(question: str, documents: list) -> str:
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


# ---------------------------------------------------------------------------
# HybridReranker
# ---------------------------------------------------------------------------

class HybridReranker:
    """
    Blends BM25 (lexical) and LLM (semantic) scores using configurable weights.
    All weights and top_k come from settings — no hardcoded values.

    Used only in the Celery task path (ProcessQuestionService).
    The streaming path uses BM25Reranker directly.
    """

    def __init__(self, top_k: int) -> None:
        self.top_k = top_k
        self.bm25_weight = settings.RERANK_BM25_WEIGHT
        self.llm_weight = settings.RERANK_LLM_WEIGHT
        self.bm25 = BM25Reranker()
        self.llm = LLMReranker()

    def rerank(self, question: str, documents: list) -> list:
        if not documents:
            return []

        top_k = self.top_k

        # --- BM25 scores ---
        try:
            tokenized_corpus = [doc.page_content.split() for doc in documents]
            bm25_model = BM25Okapi(tokenized_corpus)
            query_tokens = question.split()
            raw_bm25 = bm25_model.get_scores(query_tokens).tolist()
        except Exception as exc:
            logger.warning("[HybridReranker] BM25 scoring failed: %s", exc)
            raw_bm25 = [0.0] * len(documents)

        # --- LLM scores ---
        try:
            llm_prompt = LLMReranker._build_prompt(question, documents)
            response = self.llm.client.generate(
                model=self.llm.model,
                prompt=llm_prompt,
                format="json",   # fix: forces Ollama to return valid JSON
                stream=False,
            )
            raw_text = response["response"]
            raw_llm = _parse_llm_scores(raw_text, len(documents))  # fix: robust parser
        except RerankingError:
            raise
        except Exception as exc:
            logger.warning(
                "[HybridReranker] LLM scoring failed, using BM25 only. Error: %s", exc
            )
            raw_llm = [0.0] * len(documents)

        # --- Normalize both score lists to [0, 1] ---
        norm_bm25 = _normalize_scores(raw_bm25)
        norm_llm = _normalize_scores(raw_llm)

        # --- Blend ---
        blended = [
            self.bm25_weight * b + self.llm_weight * l
            for b, l in zip(norm_bm25, norm_llm)
        ]

        ranked = sorted(
            zip(blended, documents),
            key=lambda pair: pair[0],
            reverse=True,
        )
        return [doc for _, doc in ranked[:top_k]]
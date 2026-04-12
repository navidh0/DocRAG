"""
Reranking utilities for relevance scoring using Gemma4 LLM.
This module provides functions to rerank retrieved documents based on relevance.
"""

import os
import json
import ollama
from typing import List, Tuple


def rerank_with_gemma4(question: str, documents: List, top_k: int = 3) -> List:
    """
    Rerank retrieved documents using Gemma4 LLM for relevance scoring.
    
    Args:
        question: The user's question
        documents: List of LangChain Document objects from vector search
        top_k: Number of top documents to return
        
    Returns:
        List of reranked documents
    """
    if not documents or len(documents) == 0:
        return []
    
    try:
        client = ollama.Client(host=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
        
        # Prepare scoring prompt
        scoring_prompt = f"""You are a relevance scoring expert. Given a question and multiple document excerpts, 
score each document's relevance to the question on a scale of 0-100.

Question: {question}

Documents:
"""
        for i, doc in enumerate(documents):
            scoring_prompt += f"\n[{i}] {doc.page_content[:300]}"
        
        scoring_prompt += """\n\nProvide your scoring as a JSON object with keys "scores" containing an array of numbers.
Example: {{"scores": [85, 70, 45, 92, 60]}}
Only return valid JSON, no other text."""

        # Get scoring from Gemma4
        response = client.generate(
            model=os.getenv("LLM_MODEL", "gemma4"),
            prompt=scoring_prompt,
            stream=False
        )
        
        try:
            scores_data = json.loads(response['response'].strip())
            scores = scores_data.get('scores', [])
        except (json.JSONDecodeError, ValueError):
            # Fallback: if JSON parsing fails, use original order
            print("Failed to parse reranking scores, using original order")
            return documents[:top_k]
        
        # Pair documents with scores
        doc_score_pairs = []
        for i, doc in enumerate(documents):
            score = scores[i] if i < len(scores) else 0
            doc_score_pairs.append((score, doc))
        
        # Sort by score descending
        doc_score_pairs.sort(key=lambda x: x[0], reverse=True)
        
        # Return top-k documents
        reranked_docs = [doc for score, doc in doc_score_pairs[:top_k]]
        
        print(f"[RERANKING] Reranked {len(documents)} docs -> top {len(reranked_docs)}")
        return reranked_docs
        
    except Exception as e:
        print(f"[RERANKING ERROR] {str(e)}, returning original docs")
        return documents[:top_k]

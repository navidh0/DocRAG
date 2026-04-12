"""Optimized streaming utilities for faster time-to-first-token."""
import os
import time
import json
import hashlib
from typing import Generator, List, Dict, Any
import redis
import ollama
from langchain_postgres import PGVector
from documents.utils import get_vector_store_connection


class StreamOptimizer:
    """Handles optimized streaming with caching and parallel operations."""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.client = ollama.Client(host=self.base_url)
        self.redis_client = self._get_redis_client()
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "embeddinggemma")
        self.llm_model = os.getenv("LLM_MODEL", "gemma2")
        
    def _get_redis_client(self) -> redis.Redis:
        """Get Redis client for caching."""
        try:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            return redis.from_url(redis_url, decode_responses=True)
        except:
            # Return None if Redis not available - fallback to non-cached mode
            return None
    
    def _get_embedding_cache_key(self, text: str) -> str:
        """Generate cache key for embeddings."""
        text_hash = hashlib.md5(text.encode()).hexdigest()
        return f"embedding:{text_hash}"
    
    def get_query_embedding(self, question: str) -> List[float]:
        """
        Get query embedding with caching.
        Tries cache first, falls back to Ollama.
        """
        cache_key = self._get_embedding_cache_key(question)
        
        # Try to get from cache
        if self.redis_client:
            try:
                cached = self.redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)
            except Exception as e:
                print(f"[CACHE] Redis read failed: {e}")
        
        # Generate embedding
        try:
            print(f"[EMBEDDING] Generating embedding for: {question[:50]}...")
            start = time.time()
            response = self.client.embed(
                model=self.embedding_model,
                input=question
            )
            elapsed = int((time.time() - start) * 1000)
            print(f"[EMBEDDING] Done in {elapsed}ms")
            
            embedding = response['embeddings'][0]
            
            # Store in cache (expire after 24 hours)
            if self.redis_client:
                try:
                    self.redis_client.setex(cache_key, 86400, json.dumps(embedding))
                except Exception as e:
                    print(f"[CACHE] Redis write failed: {e}")
            
            return embedding
        except Exception as e:
            print(f"[ERROR] Embedding generation failed: {e}")
            raise
    
    def retrieve_documents(
        self, 
        query_vector: List[float], 
        user_id: str, 
        doc_id: str = None,
        k: int = 5
    ) -> List[Any]:
        """
        Retrieve relevant documents using vector similarity.
        Optimized with proper filtering and error handling.
        """
        try:
            connection = get_vector_store_connection()
            store = PGVector(
                collection_name="rag_collection",
                connection=connection,
                embeddings=None,
                use_jsonb=True,
            )
            
            # Build metadata filter for secure user isolation
            search_filter = {"user_id": str(user_id)}
            if doc_id:
                search_filter["document_id"] = str(doc_id)
            
            print(f"[RETRIEVAL] Searching for {k} documents with filter: {search_filter}")
            start = time.time()
            docs = store.similarity_search_by_vector(
                embedding=query_vector, 
                k=k, 
                filter=search_filter
            )
            elapsed = int((time.time() - start) * 1000)
            print(f"[RETRIEVAL] Found {len(docs)} documents in {elapsed}ms")
            
            return docs
        except Exception as e:
            print(f"[ERROR] Document retrieval failed: {e}")
            raise
    
    def stream_response_buffered(
        self, 
        prompt: str,
        buffer_size: int = 3
    ) -> Generator[str, None, None]:
        """
        Stream response with token buffering for efficiency.
        
        Args:
            prompt: The full prompt for the LLM
            buffer_size: Number of tokens to buffer before sending
        
        Yields:
            JSON-encoded chunks with tokens
        """
        try:
            print(f"[STREAMING] Starting stream with buffer_size={buffer_size}")
            start = time.time()
            token_count = 0
            buffer = []
            
            for chunk in self.client.generate(
                model=self.llm_model,
                prompt=prompt,
                stream=True
            ):
                token = chunk.get('response', '')
                if token:
                    buffer.append(token)
                    token_count += 1
                    
                    # Send buffered tokens
                    if len(buffer) >= buffer_size:
                        buffered_text = ''.join(buffer)
                        yield json.dumps({"token": buffered_text}) + "\n"
                        buffer = []
            
            # Send remaining buffered tokens
            if buffer:
                buffered_text = ''.join(buffer)
                yield json.dumps({"token": buffered_text}) + "\n"
            
            elapsed = int((time.time() - start) * 1000)
            print(f"[STREAMING] Complete: {token_count} tokens in {elapsed}ms")
            
        except Exception as e:
            print(f"[ERROR] Streaming failed: {e}")
            raise
    
    def extract_sources(self, docs: List[Any]) -> List[Dict[str, Any]]:
        """Extract and format source citations from documents."""
        sources = []
        for doc in docs:
            meta = doc.metadata
            sources.append({
                "file_name": meta.get("file_name", "Unknown"),
                "page": meta.get("page", 1),
                "chunk_index": meta.get("chunk_index", 0),
                "excerpt": doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content
            })
        return sources


def create_optimized_prompt(context: str, question: str) -> str:
    """Create a well-structured prompt for the LLM."""
    return f"""Context:
{context}

Question:
{question}

Answer Instructions:
- Base your answer ONLY on the provided context
- Be concise and direct
- If the context doesn't contain relevant information, say so
- Include specific references from the context when possible

Answer:"""

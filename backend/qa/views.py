import os
import time
import json
from urllib import request
import ollama
from django.http import StreamingHttpResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from langchain_postgres import PGVector
from django.utils import timezone
from .models import QuestionActivity
from .reranking import rerank_with_gemma4
from .streaming import StreamOptimizer, create_optimized_prompt
from documents.utils import get_vector_store_connection


class QuestionAnsweringView(APIView):
    """Answer questions based on user's uploaded documents"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        POST /api/qa/ask/
        Answer a question using retrieved context from user documents.

        Request body:
            - question (required): string
            - document_id (optional): UUID of specific document to search
            - page (optional): 1-based page number (converted to 0-based internally)
        """
        question = request.data.get('question')
        doc_id = request.data.get('document_id')
        page_filter = request.data.get('page')
        start_time = time.time()

        if not question or question.strip() == "":
            return Response({"error": "Question is required"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            # 1. Generate query embedding
            client = ollama.Client(host=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
            q_response = client.embed(
                model=os.getenv("EMBEDDING_MODEL", "embeddinggemma"),
                input=question
            )
            query_vector = q_response['embeddings'][0]

            # 2. Setup vector store
            connection = get_vector_store_connection()
            store = PGVector(
                collection_name="rag_collection",
                connection=connection,
                embeddings=None,
                use_jsonb=True,
            )

            # 3. Build metadata filter
            # - user_id is always applied for strict data isolation
            # - document_id narrows search to one document when provided
            # - page is stored 0-indexed in JSONB; user supplies 1-based value
            # - chunk_index is intentionally excluded: it over-constrains the
            #   vector search to a single chunk and causes empty results
            search_filter = {"user_id": str(request.user.id)}

            if doc_id:
                search_filter["document_id"] = str(doc_id)

            if page_filter is not None:
                try:
                    search_filter["page"] = int(page_filter) - 1
                except (ValueError, TypeError):
                    return Response({"error": "Invalid page number"}, status=status.HTTP_400_BAD_REQUEST)

            # 4. Retrieve relevant chunks
            docs = store.similarity_search_by_vector(
                embedding=query_vector,
                k=5,
                filter=search_filter,
            )

            if not docs:
                return Response({
                    "answer": "I could not find relevant information in your documents.",
                    "sources": [],
                    "status": "no_answer"
                }, status=200)

            # 5. Rerank for better relevance
            reranked_docs = rerank_with_gemma4(question, docs, top_k=3)
            docs = reranked_docs if reranked_docs else docs[:3]

            # 6. Generate answer
            context_parts = []
            for d in docs:
                meta = d.metadata
                context_parts.append(
                    f"[Document: {meta.get('file_name', 'Unknown')} | Page: {meta.get('page', 0) + 1} | Chunk: {meta.get('chunk_index', 0)}]\n"
                    f"{d.page_content}"
                )

            context = "\n\n".join(context_parts)
            prompt = f"""
                You are a document question-answering assistant.

                IMPORTANT RULES:
                - The context consists of retrieved chunks from documents.
                - Each chunk includes metadata like [Page: X].
                - Multiple chunks from the same page together represent that page.
                - The context may be partial, but you MUST use it to answer.

                STRICT INSTRUCTIONS:
                - Answer ONLY using the provided context.
                - If the question refers to a specific page (e.g., "page 2"), use the metadata.
                - DO NOT say the page does not exist if chunks from that page are present.
                - If information is partial, provide the best possible answer.
                - If truly not enough information exists, say: "Not available in the provided documentation."

                Context:
                {context}

                Question:
                {question}

                Answer:
                """

            response = client.generate(
                model=os.getenv("LLM_MODEL", "gemma4:e4b"),
                prompt=prompt,
                stream=False
            )
            answer = response['response'].strip()

            # 7. Build source citations
            # page is stored 0-indexed in DB; convert back to 1-based for the response
            sources = []
            for doc in docs:
                meta = doc.metadata
                sources.append({
                    "file_name": meta.get("file_name", "Unknown"),
                    "page": meta.get("page", 0) + 1,
                    "chunk_index": meta.get("chunk_index", 0),
                    "excerpt": doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content
                })

            # 8. Log activity
            execution_time = int((time.time() - start_time) * 1000)
            QuestionActivity.objects.create(
                user=request.user,
                document_id=doc_id if doc_id else None,
                question=question,
                answer=answer,
                sources=sources,
                response_time_ms=execution_time,
                status="success"
            )

            return Response({
                "answer": answer,
                "sources": sources,
                "response_time_ms": execution_time,
                "status": "success"
            }, status=200)

        except Exception as e:
            print(f"[ERROR] QA processing failed: {str(e)}")
            import traceback
            traceback.print_exc()

            execution_time = int((time.time() - start_time) * 1000)
            QuestionActivity.objects.create(
                user=request.user,
                document_id=doc_id if doc_id else None,
                question=question,
                answer="An error occurred while processing your question.",
                sources=[],
                response_time_ms=execution_time,
                status="error"
            )
            return Response({
                "error": "An error occurred while processing your question.",
                "status": "error"
            }, status=status.HTTP_400_BAD_REQUEST)

class ChatStreamView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        question = request.data.get('question')
        doc_id = request.data.get('document_id')
        start_time = time.time()

        if not question or question.strip() == "":
            return Response(
                {"error": "Question is required"},
                status=400
            )

        try:
            optimizer = StreamOptimizer()
            
            # 1. Get cached or generated embedding
            print(f"[STREAM] Processing question: {question[:60]}...")
            query_vector = optimizer.get_query_embedding(question)
            
            # 2. Retrieve relevant documents (happens in parallel with prompt prep)
            docs = optimizer.retrieve_documents(
                query_vector=query_vector,
                user_id=str(request.user.id),
                doc_id=doc_id,
                k=5
            )
            
            if not docs:
                return Response({
                    "answer": "I could not find relevant information in your documents to answer this question.",
                    "sources": [],
                    "status": "no_answer"
                }, status=200)
            
            # 3. Rerank for relevance
            reranked_docs = rerank_with_gemma4(question, docs, top_k=3)
            docs = reranked_docs if reranked_docs else docs[:3]
            
            # 4. Extract sources
            sources = optimizer.extract_sources(docs)
            
            # 5. Create optimized prompt
            context = "\n\n".join([d.page_content for d in docs])
            prompt = create_optimized_prompt(context, question)
            
            # 6. Streaming generator with logging
            def stream_generator():
                full_response = ""
                try:
                    # Stream with buffering for efficiency
                    for buffered_chunk in optimizer.stream_response_buffered(prompt, buffer_size=3):
                        chunk_data = json.loads(buffered_chunk.strip())
                        token = chunk_data.get('token', '')
                        full_response += token
                        yield buffered_chunk
                    
                    # Log activity after stream completes
                    execution_time = int((time.time() - start_time) * 1000)
                    print(f"[STREAM] Completed in {execution_time}ms, {len(full_response)} chars")
                    QuestionActivity.objects.create(
                        user=request.user,
                        document_id=doc_id if doc_id else None,
                        question=question,
                        answer=full_response,
                        sources=sources,
                        response_time_ms=execution_time,
                        status="success"
                    )
                except Exception as e:
                    print(f"[ERROR] Stream error: {str(e)}")
                    execution_time = int((time.time() - start_time) * 1000)
                    QuestionActivity.objects.create(
                        user=request.user,
                        document_id=doc_id if doc_id else None,
                        question=question,
                        answer="Stream interrupted due to error.",
                        sources=sources,
                        response_time_ms=execution_time,
                        status="error"
                    )
                    yield json.dumps({"error": "Stream interrupted"}) + "\n"

            # Return streaming response with JSON newline format
            return StreamingHttpResponse(
                stream_generator(), 
                content_type='application/x-ndjson'
            )

        except Exception as e:
            print(f"[ERROR] Stream setup failed: {str(e)}")
            import traceback
            traceback.print_exc()
            return Response({
                "error": "An error occurred while setting up the stream.",
                "status": "error"
            }, status=500)

class QuestionActivityListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Get user's question history and statistics"""
        try:
            # Get all questions for the user
            activities = QuestionActivity.objects.filter(
                user=request.user
            ).order_by('-created_at')
            
            # Apply optional filters
            status_filter = request.query_params.get('status')
            if status_filter:
                activities = activities.filter(status=status_filter)
            
            doc_id = request.query_params.get('document_id')
            if doc_id:
                activities = activities.filter(document_id=doc_id)
            
            # Pagination
            page = int(request.query_params.get('page', 1))
            page_size = int(request.query_params.get('page_size', 20))
            start = (page - 1) * page_size
            end = start + page_size
            
            total_count = activities.count()
            paginated_activities = activities[start:end]
            
            # Serialize data
            data = {
                "total_questions": total_count,
                "questions_today": QuestionActivity.objects.filter(
                    user=request.user,
                    created_at__date=timezone.now().date()   # ✅ use today's date
                ).count(),
                "page": page,
                "page_size": page_size,
                "total_pages": (total_count + page_size - 1) // page_size,
                "activities": []
            }
            
            for activity in paginated_activities:
                data["activities"].append({
                    "id": activity.id,
                    "question": activity.question,
                    "answer": activity.answer[:200] + "..." if len(activity.answer) > 200 else activity.answer,
                    "document_id": activity.document_id,
                    "sources_count": len(activity.sources) if activity.sources else 0,
                    "response_time_ms": activity.response_time_ms,
                    "status": activity.status,
                    "created_at": activity.created_at.isoformat()
                })
            
            return Response(data, status=200)
            
        except Exception as e:
            print(f"Error fetching activity: {str(e)}")
            return Response({
                "error": "An error occurred while fetching activity.",
                "status": "error"
            }, status=500)
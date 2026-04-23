import os
import ollama
from rest_framework import generics, filters, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.conf import settings
from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from langchain_postgres import PGVector
from .models import Document
from .serializers import DocumentSerializer
from .tasks import process_document_embedding
from .utils import get_vector_store_connection
from .services import (
    CreateDocumentService
)

class DocumentListCreateView(generics.ListCreateAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['file_type', 'status']
    search_fields = ['file_name']
    ordering_fields = ['created_at', 'file_name']
    ordering = ['-created_at']

    def get_queryset(self):
        return Document.objects.filter(user=self.request.user)

    def perform_create(self, serializer): 
        CreateDocumentService.execute(
            user=self.request.user, validated_data=serializer.validated_data
            )
        serializer.save(user=self.request.user)


class DocumentRetrieveUpdateDestroyView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = DocumentSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        return Document.objects.filter(user=self.request.user)

    def destroy(self, request, *args, **kwargs):
        """Override to provide a response body on deletion."""
        instance = self.get_object()
        doc_id = instance.id
        file_name = instance.file_name
        
        self.perform_destroy(instance)
        
        return Response({
            "message": "Document deleted successfully",
            "details": {
                "id": str(doc_id),
                "file_name": file_name
            }
        }, status=status.HTTP_200_OK)


class DocumentStatusView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request, id):
        try:
            doc = Document.objects.get(id=id, user=request.user)
            return Response({
                "id": str(doc.id),
                "file_name": doc.file_name,
                "status": doc.status,
                "created_at": doc.created_at.isoformat(),
                "status_description": self.get_status_description(doc.status)
            }, status=status.HTTP_200_OK)
        except Document.DoesNotExist:
            return Response({"error": "Document not found"}, status=status.HTTP_404_NOT_FOUND)
    
    @staticmethod
    def get_status_description(doc_status):
        descriptions = {
            'pending': 'Waiting to be processed',
            'processing': 'Extracting text and generating embeddings...',
            'completed': 'Ready for Q&A',
            'failed': 'Processing failed. Check file format or logs.',
        }
        return descriptions.get(doc_status, 'Unknown status')


class DocumentChunksDebugView(APIView):
    """Utility to verify chunks exist in the vector database"""
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        connection = get_vector_store_connection()
        
        try:
            store = PGVector(
                collection_name="rag_collection",
                connection=connection,
                embeddings=None, 
                use_jsonb=True,
            )

            # Generate a dummy query embedding to retrieve chunks
            client = ollama.Client(host=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
            dummy_query = "document"
            q_emb_resp = client.embed(
                model=os.getenv("EMBEDDING_MODEL", "embeddinggemma"),
                input=dummy_query
            )
            query_vector = q_emb_resp['embeddings'][0]

            # Query chunks by metadata and vector similarity
            chunks = store.similarity_search_by_vector(
                embedding=query_vector, 
                k=100, 
                filter={"document_id": str(id), "user_id": str(request.user.id)}
            )

            return Response({
                "document_id": id,
                "total_chunks_found": len(chunks),
                "chunks": [{"content": c.page_content[:150], "metadata": c.metadata} for c in chunks]
            })
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
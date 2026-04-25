from rest_framework import generics, filters, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from langchain_postgres import PGVector

from .services import (
    CreateDocumentService,
    GetDocumentStatusService,
    DeleteDocumentService,
    DebugDocumentChunksService,
)
from .serializers import (
    DocumentStatusOutputSerializer,
    DocumentOutputSerializer,
    DocumentUploadInputSerializer,
)
from .selectors import(
    document_list,
)

class DocumentListCreateView(generics.ListCreateAPIView):
    serializer_class = DocumentOutputSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['file_type', 'status']
    search_fields = ['file_name']
    ordering_fields = ['created_at', 'file_name']
    ordering = ['-created_at']

    def get_queryset(self):
        return document_list(user=self.request.user)

    def create(self, request, *args, **kwargs):
        input_ser = DocumentUploadInputSerializer(data=request.data)
        input_ser.is_valid(raise_exception=True)
        doc = CreateDocumentService.execute(
            user=request.user,
            validated_data=input_ser.validated_data,
        )
        output_ser = DocumentOutputSerializer(doc)
        return Response(output_ser.data, status=status.HTTP_201_CREATED)

class DocumentRetrieveDestroyView(generics.RetrieveDestroyAPIView):
    serializer_class = DocumentOutputSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'id'

    def get_queryset(self):
        return document_list(user=self.request.user)

    def destroy(self, request, *args, **kwargs):
        data = DeleteDocumentService.execute(
            user=request.user,
            document_id=kwargs['id'],
        )
        return Response({
            "message": "Document deleted successfully",
            "details": data,
        }, status=status.HTTP_200_OK)


class DocumentStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        data = GetDocumentStatusService.execute(
            user=request.user,
            document_id=id,
        )
        output = DocumentStatusOutputSerializer(data)
        return Response(output.data, status=status.HTTP_200_OK)
    
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
    """Utility to verify chunks exist in the vector database."""
    permission_classes = [IsAuthenticated]

    def get(self, request, id):
        data = DebugDocumentChunksService.execute(
            user=request.user,
            document_id=id,
        )
        return Response(data, status=status.HTTP_200_OK)
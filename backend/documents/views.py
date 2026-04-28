from rest_framework import generics, filters, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import (
    extend_schema, 
    OpenApiResponse, 
)
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
    document_get,
)

# @extend_schema(
#     methods=['POST'],
#     request={
#         'multipart/form-data': {
#             'type': 'object',
#             'properties': {
#                 'file': {
#                     'type': 'string',
#                     'format': 'binary',
#                 },
#             },
#             'required': ['file'],
#         }
#     },
#     responses={201: DocumentOutputSerializer},
# )
# class DocumentListCreateView(generics.ListCreateAPIView):
#     serializer_class = DocumentOutputSerializer
#     permission_classes = [IsAuthenticated]
#     parser_classes = [MultiPartParser, FormParser]
#     filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
#     filterset_fields = ['file_type', 'status']
#     search_fields = ['file_name']
#     ordering_fields = ['created_at', 'file_name']
#     ordering = ['-created_at']

#     def get_queryset(self):
#         return document_list(user=self.request.user)
    
#     def create(self, request, *args, **kwargs):
#         input_ser = DocumentUploadInputSerializer(data=request.data)
#         input_ser.is_valid(raise_exception=True)
#         doc = CreateDocumentService.execute(
#             user=request.user,
#             validated_data=input_ser.validated_data,
#         )
#         output_ser = DocumentOutputSerializer(doc)
#         return Response(output_ser.data, status=status.HTTP_201_CREATED)

# @extend_schema(
#     methods=['DELETE'],
#     responses={
#         200: OpenApiResponse(description="Document deleted successfully"),
#         404: OpenApiResponse(description="Document not found"),
#     },
# )
# @extend_schema(
#     methods=['GET'],
#     responses={200: DocumentOutputSerializer},
# )
class DocumentListCreateView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(responses={200: DocumentOutputSerializer(many=True)})
    def get(self, request):
        documents = document_list(user=request.user, filters=request.query_params)
        paginator = PageNumberPagination()
        paginated_qs = paginator.paginate_queryset(documents, request, view=self)
        output = DocumentOutputSerializer(paginated_qs, many=True)
        
        return Response(
        paginator.get_paginated_response(output.data).data,
        status=status.HTTP_200_OK
        )

    @extend_schema(
        request={
            'multipart/form-data': {
                'type': 'object',
                'properties': {'file': {'type': 'string', 'format': 'binary'}},
                'required': ['file'],
            }
        },
        responses={201: DocumentOutputSerializer},
    )
    def post(self, request):
        input_ser = DocumentUploadInputSerializer(data=request.data)
        input_ser.is_valid(raise_exception=True)
        doc = CreateDocumentService.execute(
            user=request.user,
            validated_data=input_ser.validated_data,
        )
        output = DocumentOutputSerializer(doc)
        return Response(output.data, status=status.HTTP_201_CREATED)

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

    @extend_schema(
        responses={
            200: DocumentStatusOutputSerializer,
            404: OpenApiResponse(description="Document not found"),
        }
    )
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

    @extend_schema(
        responses={
            200: OpenApiResponse(description="List of chunks for the document"),
        }
    )
    def get(self, request, id):
        data = DebugDocumentChunksService.execute(
            user=request.user,
            document_id=id,
        )
        return Response(data, status=status.HTTP_200_OK)
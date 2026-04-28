from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from rest_framework import status
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.pagination import PageNumberPagination
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

class DocumentListCreateView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(responses={200: DocumentOutputSerializer(many=True)})
    def get(self, request: Request) -> Response:

        documents = document_list(
            user=request.user, 
            filters=cast(dict[str, str], request.query_params.dict())
            )
        
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
    def post(self, request: Request) -> Response:
        input_ser = DocumentUploadInputSerializer(data=request.data)
        input_ser.is_valid(raise_exception=True)
        doc = CreateDocumentService.execute(
            user=request.user,
            validated_data=cast(dict[str, Any], input_ser.validated_data),
        )
        output = DocumentOutputSerializer(doc)
        return Response(output.data, status=status.HTTP_201_CREATED)

class DocumentRetrieveDestroyView(APIView):

    @extend_schema(responses={200: DocumentOutputSerializer})
    def get(self, request: Request, id: UUID) -> Response:
        doc = document_get(user=request.user, document_id=id)
        output = DocumentOutputSerializer(doc)
        return Response(output.data, status=status.HTTP_200_OK)

    @extend_schema(
        responses={
            200: OpenApiResponse(description="Document deleted successfully"),
            404: OpenApiResponse(description="Document not found"),
        }
    )
    def delete(self, request: Request, id: UUID) -> Response:
        data = DeleteDocumentService.execute(user=request.user, document_id=id)
        return Response(
            {"message": "Document deleted successfully", "details": data},
            status=status.HTTP_200_OK,
        )
    
class DocumentStatusView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: DocumentStatusOutputSerializer,
            404: OpenApiResponse(description="Document not found"),
        }
    )
    def get(self, request: Request, id: UUID) -> Response:
        data = GetDocumentStatusService.execute(
            user=request.user,
            document_id=id,
        )
        output = DocumentStatusOutputSerializer(data)
        return Response(output.data, status=status.HTTP_200_OK)
    
    @staticmethod
    def get_status_description(doc_status):
        descriptions: dict[str, str] = {
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
    def get(self, request: Request, id: UUID) -> Response:
        data = DebugDocumentChunksService.execute(
            user=request.user,
            document_id=id,
        )
        return Response(data, status=status.HTTP_200_OK)
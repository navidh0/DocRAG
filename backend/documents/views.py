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
    OpenApiParameter,
    OpenApiResponse,
)
from drf_spectacular.types import OpenApiTypes

from .serializers import (
    DocumentListFilterSerializer,
    DocumentOutputSerializer,
    DocumentStatusOutputSerializer,
    DocumentStatusWithChunksOutputSerializer,
    DocumentUploadInputSerializer,
    STATUS_CHOICES,
    FILE_TYPE_CHOICES,
)
from .services import (
    CreateDocumentService,
    GetDocumentStatusService,
    DeleteDocumentService,
    DocumentChunksService,
)
from .selectors import document_list, document_get


class DocumentListCreateView(APIView):
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="List uploaded documents",
        description=(
            "Returns a paginated list of documents uploaded by the authenticated user, "
            "ordered by upload date descending."
        ),
        parameters=[
            OpenApiParameter(
                name="search",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Case-insensitive partial match against file name.",
            ),
            OpenApiParameter(
                name="file_type",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=FILE_TYPE_CHOICES,
                description="Filter by exact file type.",
            ),
            OpenApiParameter(
                name="status",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=STATUS_CHOICES,
                description="Filter by processing status.",
            ),
        ],
        responses={
            200: DocumentOutputSerializer(many=True),
        },
    )
    def get(self, request: Request) -> Response:
        filter_ser = DocumentListFilterSerializer(data=request.query_params)
        filter_ser.is_valid(raise_exception=True)

        documents = document_list(
            user=request.user,
            filters=filter_ser.validated_data, #type: ignore
        )

        paginator = PageNumberPagination()
        paginated_qs = paginator.paginate_queryset(documents, request, view=self)
        output = DocumentOutputSerializer(paginated_qs, many=True)

        return Response(
            paginator.get_paginated_response(output.data).data,
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Upload a document",
        description=(
            "Upload a document to be asynchronously processed and indexed for Q&A retrieval. "
            "After upload, the document enters `pending` status. "
            "Poll `GET /documents/{id}/status/` to track progress through "
            "`processing` → `completed` (or `failed`). "
            "Supported formats: **PDF, XLSX, XLS, TXT, CSV**."
        ),
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "file": {
                        "type": "string",
                        "format": "binary",
                        "description": "The document file to upload.",
                    }
                },
                "required": ["file"],
            }
        },
        responses={
            201: DocumentOutputSerializer,
            400: OpenApiResponse(
                description=(
                    "Validation error — file missing or extension not in the allowed set "
                    "(pdf, xlsx, xls, txt, csv)."
                )
            ),
        },
    )
    def post(self, request: Request) -> Response:
        input_ser = DocumentUploadInputSerializer(data=request.data)
        input_ser.is_valid(raise_exception=True)

        doc = CreateDocumentService.execute(
            user=request.user,
            validated_data=cast(dict[str, Any], input_ser.validated_data),
        )

        return Response(DocumentOutputSerializer(doc).data, status=status.HTTP_201_CREATED)


class DocumentRetrieveDestroyView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Retrieve document",
        description=(
            "Returns core metadata for a single document: "
            "ID, file name, file type, processing status, and upload timestamp. "
            "Use `GET /documents/{id}/status/` for full processing detail and optional chunk inspection."
        ),
        responses={
            200: DocumentOutputSerializer,
            404: OpenApiResponse(
                description="Document not found or does not belong to the authenticated user."
            ),
        },
    )
    def get(self, request: Request, id: UUID) -> Response:
        doc = document_get(user=request.user, document_id=id)
        return Response(DocumentOutputSerializer(doc).data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Delete a document",
        description=(
            "Permanently deletes the document and all associated vector embeddings. "
            "**This action is irreversible.** "
            "Returns the ID and file name of the deleted document for confirmation."
        ),
        responses={
            200: OpenApiResponse(
                description="Document deleted. Body: `{message, details: {id, file_name}}`."
            ),
            404: OpenApiResponse(
                description="Document not found or does not belong to the authenticated user."
            ),
        },
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
        summary="Get document processing status",
        description=(
            "Returns full processing detail for a document: status, human-readable "
            "description, and upload timestamp.\n\n"
            "**Chunk inspection** — pass `?include_chunks=true` to append a preview of every "
            "vector chunk indexed for this document (first 150 chars of content + typed metadata). "
            "The fields `total_chunks` and `chunks` are only present in the response when this "
            "flag is `true`. Intended for development and debugging; avoid in hot paths."
        ),
        parameters=[
            OpenApiParameter(
                name="include_chunks",
                type=OpenApiTypes.BOOL,
                location=OpenApiParameter.QUERY,
                required=False,
                default=False,
                description=(
                    "When `true`, response includes `total_chunks` (int) and "
                    "`chunks` (list of `{content, metadata}`). Omitted when `false` (default)."
                ),
            ),
        ],
        responses={
            200: DocumentStatusWithChunksOutputSerializer,
            404: OpenApiResponse(
                description="Document not found or does not belong to the authenticated user."
            ),
        },
    )
    def get(self, request: Request, id: UUID) -> Response:
        data = GetDocumentStatusService.execute(
            user=request.user,
            document_id=id,
        )

        include_chunks = (
            request.query_params.get("include_chunks", "false").lower() == "true"
        )

        if include_chunks:
            chunks_data = DocumentChunksService.execute(
                user=request.user,
                document_id=id,
            )
            data["total_chunks"] = chunks_data["total_chunks_found"]
            data["chunks"] = chunks_data["chunks"]
            serializer = DocumentStatusWithChunksOutputSerializer(data)
        else:
            serializer = DocumentStatusOutputSerializer(data)

        return Response(serializer.data, status=status.HTTP_200_OK)
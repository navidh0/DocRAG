from __future__ import annotations

from typing import cast, Dict, Any

from django.http import StreamingHttpResponse
from rest_framework import serializers as drf_serializers
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from drf_spectacular.types import OpenApiTypes

from .pagination import QuestionActivityPagination
from .selectors import QuestionActivityListFilters, question_activity_list, question_activity_stats
from .serializers import (
    AskQuestionInputSerializer,
    AskQuestionOutputSerializer,
    QuestionActivityListFilterSerializer,
    QuestionActivityOutputSerializer,
    QuestionResultOutputSerializer,
    STATUS_CHOICES,
    StreamQuestionInputSerializer,
)
from .services import (
    AskQuestionService,
    GetQuestionResultService,
    StreamQuestionService,
)


class QuestionAnsweringView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["QA"],
        summary="Submit a question for async processing",
        description=(
            "Submits a question to the RAG pipeline and returns a `task_id` immediately. "
            "Embedding generation, vector retrieval, hybrid reranking, and LLM generation "
            "all run asynchronously in a Celery worker.\n\n"
            "**Flow:**\n"
            "1. `POST /api/qa/ask/` — receive `task_id` with `status: processing` (202)\n"
            "2. Poll `GET /api/qa/result/{task_id}/` until `status` is no longer `processing`\n\n"
            "Optionally scope retrieval to a single document via `document_id`, "
            "or to a specific page (1-based) via `page`. "
            "Use `POST /api/qa/stream/` if you prefer a streaming response."
        ),
        request=AskQuestionInputSerializer,
        responses={
            202: AskQuestionOutputSerializer,
            400: OpenApiResponse(
                description="Validation error — question is blank or field types are invalid."
            ),
        },
        examples=[
            OpenApiExample(
                name="Global question",
                summary="Question across all documents",
                request_only=True,
                value={"question": "Summarise all uploaded documents."},
            ),
            OpenApiExample(
                name="Scoped question",
                summary="Question scoped to a document and page",
                request_only=True,
                value={
                    "question": "What are the key findings in the annual report?",
                    "document_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "page": 4,
                },
            ),
            OpenApiExample(
                name="Accepted",
                summary="Task accepted, poll for result",
                response_only=True,
                status_codes=["202"],
                value={
                    "task_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "status": "processing",
                },
            ),
        ],
    )
    def post(self, request):
        input_serializer = AskQuestionInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        validated_data = cast(Dict[str, Any], input_serializer.validated_data)
        result = AskQuestionService.execute(
            user=request.user,
            validated_data=validated_data,
        )
        return Response(
            AskQuestionOutputSerializer(result).data,
            status=status.HTTP_202_ACCEPTED,
        )

class QuestionResultView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["QA"],
        summary="Poll question result",
        description=(
            "Retrieves the result of an async question submitted via `POST /api/qa/ask/`.\n\n"
            "**Response by status:**\n\n"
            "| `status` | HTTP | Meaning |\n"
            "|---|---|---|\n"
            "| `processing` | 202 | Worker hasn't finished — poll again |\n"
            "| `success` | 200 | Answer and sources are present |\n"
            "| `no_answer` | 200 | No relevant chunks found in the documents |\n"
            "| `error` | 200 | LLM generation failed inside the worker |\n\n"
            "Poll at a reasonable cadence (e.g. every 1–2 s). "
            "Task results expire after the Celery result backend TTL "
            "— a missing task returns 404."
        ),
        parameters=[
            OpenApiParameter(
                name="task_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.PATH,
                description="The task ID returned by `POST /api/qa/ask/`.",
            ),
        ],
        responses={
            200: QuestionResultOutputSerializer,
            202: OpenApiResponse(
                response=QuestionResultOutputSerializer,
                description="Question is still being processed. Poll again shortly.",
            ),
            404: OpenApiResponse(
                description="Task ID not found or result has expired."
            ),
            500: OpenApiResponse(
                description="Question processing failed inside the Celery worker."
            ),
        },
        examples=[
            OpenApiExample(
                name="Still processing",
                response_only=True,
                status_codes=["202"],
                value={
                    "task_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "status": "processing",
                },
            ),
            OpenApiExample(
                name="Success",
                response_only=True,
                status_codes=["200"],
                value={
                    "task_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "status": "success",
                    "answer": "The key findings include a 12% revenue increase year-over-year...",
                    "sources": [
                        {
                            "file_name": "annual_report_2024.pdf",
                            "page": 4,
                            "chunk_index": 2,
                            "excerpt": "Revenue grew by 12% year-over-year driven by...",
                        }
                    ],
                    "response_time_ms": 1843,
                },
            ),
            OpenApiExample(
                name="No answer",
                response_only=True,
                status_codes=["200"],
                value={
                    "task_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "status": "no_answer",
                    "answer": "I could not find relevant information in the provided documents.",
                    "sources": [],
                    "response_time_ms": 312,
                },
            ),
        ],
    )
    def get(self, request, task_id):
        result = GetQuestionResultService.execute(task_id=str(task_id))
        http_status = (
            status.HTTP_202_ACCEPTED
            if result["status"] == "processing"
            else status.HTTP_200_OK
        )
        return Response(
            QuestionResultOutputSerializer(result).data,
            status=http_status,
        )


class ChatStreamView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["QA"],
        summary="Stream an answer via NDJSON",
        description=(
            "Submits a question and streams the answer as newline-delimited JSON (NDJSON). "
            "Each line in the response body is a self-contained JSON object; "
            "parse line by line with `JSON.parse(line)` as data arrives.\n\n"
            "**Chunk shapes** — discriminated by the `status` field:\n\n"
            "| Shape | Condition | Fields |\n"
            "|---|---|---|\n"
            "| Token | During LLM generation | `token` (str), `status: 'streaming'` |\n"
            "| No-answer | No relevant chunks found | `status: 'no_answer'`, `answer` (str) |\n"
            "| Error | Mid-stream failure | `status: 'error'`, `error` (str) |\n\n"
            "Concatenate `token` values in arrival order to reconstruct the full answer. "
            "The stream closes after the terminal chunk (no-answer or error) "
            "or naturally after generation completes.\n\n"
            "**Error before stream opens** — embedding or retrieval failures are returned "
            "as standard DRF error responses (503 / 500) before any NDJSON is emitted. "
            "Use `POST /api/qa/ask/` if you prefer an async polling model."
        ),
        request=StreamQuestionInputSerializer,
        responses={
            200: OpenApiResponse(
                description=(
                    "NDJSON stream. Each newline-terminated line is one of the three "
                    "chunk shapes described above. Content-Type: application/x-ndjson."
                ),
                response=inline_serializer(
                    name="NdjsonChunk",
                    fields={
                        "token": drf_serializers.CharField(
                            required=False,
                            help_text=(
                                "A fragment of the generated answer. "
                                "Present only in token chunks (status='streaming')."
                            ),
                        ),
                        "status": drf_serializers.ChoiceField(
                            choices=["streaming", "no_answer", "error"],
                            help_text="Discriminator — identifies which chunk shape this is.",
                        ),
                        "answer": drf_serializers.CharField(
                            required=False,
                            help_text=(
                                "Terminal message when no relevant documents were found. "
                                "Present only in no-answer chunks."
                            ),
                        ),
                        "error": drf_serializers.CharField(
                            required=False,
                            help_text=(
                                "Error message describing a mid-stream failure. "
                                "Present only in error terminal chunks."
                            ),
                        ),
                    },
                ),
            ),
            400: OpenApiResponse(
                description="Validation error — question is blank or document_id is malformed."
            ),
            503: OpenApiResponse(
                description=(
                    "Embedding service unavailable. "
                    "Raised before the stream opens — response is standard JSON."
                )
            ),
            500: OpenApiResponse(
                description=(
                    "Document retrieval failed. "
                    "Raised before the stream opens — response is standard JSON."
                )
            ),
        },
        examples=[
            OpenApiExample(
                name="Token chunk",
                summary="Mid-generation token fragment",
                response_only=True,
                status_codes=["200"],
                value={"token": "The key findings include", "status": "streaming"},
            ),
            OpenApiExample(
                name="No-answer terminal",
                summary="Terminal chunk — no relevant content found",
                response_only=True,
                status_codes=["200"],
                value={
                    "status": "no_answer",
                    "answer": "No relevant information found.",
                },
            ),
            OpenApiExample(
                name="Error terminal",
                summary="Terminal chunk — mid-stream failure",
                response_only=True,
                status_codes=["200"],
                value={"status": "error", "error": "Stream interrupted."},
            ),
        ],
    )
    def post(self, request):
        input_serializer = StreamQuestionInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        validated_data = cast(Dict[str, Any], input_serializer.validated_data)
        generator = StreamQuestionService.execute(
            user=request.user,
            validated_data=validated_data,
        )
        return StreamingHttpResponse(
            (chunk.encode("utf-8") for chunk in generator),
            content_type="application/x-ndjson",
            status=status.HTTP_200_OK,
        )


class QuestionActivityListView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["QA"],
        summary="List question activity history",
        description=(
            "Returns a paginated list of the authenticated user's past Q&A interactions, "
            "ordered by most recent first.\n\n"
            "**Filtering:**\n"
            "- `status` — narrow to a specific outcome (`success`, `no_answer`, `error`)\n"
            "- `document_id` — scope history to one document; "
            "returns 404 if the document is not found or belongs to another user\n\n"
            "**Envelope fields:**\n"
            "- `total_questions` — total matching activities respecting active filters\n"
            "- `questions_today` — today's count for the user, always unfiltered "
            "(suitable for dashboard display)\n"
            "- `activities` — the paginated activity objects for this page"
        ),
        parameters=[
            OpenApiParameter(
                name="status",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=STATUS_CHOICES,
                description="Filter by question outcome.",
            ),
            OpenApiParameter(
                name="document_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Scope activity history to a specific document. "
                    "Returns 404 if the document does not belong to the authenticated user."
                ),
            ),
            OpenApiParameter(
                name="page",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Page number (default: 1).",
            ),
            OpenApiParameter(
                name="page_size",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Items per page. Controlled by `page_size_query_param`.",
            ),
        ],
        responses={
            200: OpenApiResponse(
                description="Paginated activity history with dashboard stats.",
                response=inline_serializer(
                    name="PaginatedQuestionActivityResponse",
                    fields={
                        "total_questions": drf_serializers.IntegerField(
                            help_text=(
                                "Total activities matching the active filters. "
                                "Use for pagination controls."
                            ),
                        ),
                        "questions_today": drf_serializers.IntegerField(
                            help_text=(
                                "Questions asked today by this user, unfiltered. "
                                "Suitable for a dashboard counter."
                            ),
                        ),
                        "page": drf_serializers.IntegerField(
                            help_text="Current page number (1-based).",
                        ),
                        "page_size": drf_serializers.IntegerField(
                            help_text="Number of items on this page.",
                        ),
                        "total_pages": drf_serializers.IntegerField(
                            help_text="Total number of available pages.",
                        ),
                        "activities": QuestionActivityOutputSerializer(many=True),
                    },
                ),
            ),
            400: OpenApiResponse(
                description="Invalid filter parameter — unknown status value or malformed UUID."
            ),
            404: OpenApiResponse(
                description=(
                    "The specified `document_id` was not found or does not belong "
                    "to the authenticated user."
                ),
            ),
        },
        examples=[
            OpenApiExample(
                name="Paginated response",
                response_only=True,
                status_codes=["200"],
                value={
                    "total_questions": 42,
                    "questions_today": 7,
                    "page": 1,
                    "page_size": 10,
                    "total_pages": 5,
                    "activities": [
                        {
                            "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                            "question": "What are the key findings?",
                            "answer": "The key findings include a 12% revenue increase...",
                            "document_id": "7cb12f64-1234-4562-b3fc-2c963f66afa6",
                            "sources_count": 3,
                            "response_time_ms": 1843,
                            "status": "success",
                            "created_at": "2024-01-15T10:30:00Z",
                        }
                    ],
                },
            ),
        ],
    )
    def get(self, request):
        filter_ser = QuestionActivityListFilterSerializer(data=request.query_params)
        filter_ser.is_valid(raise_exception=True)

        activities = question_activity_list(
            user=request.user,
            filters=cast(QuestionActivityListFilters, filter_ser.validated_data),
        )
        stats = question_activity_stats(user=request.user)

        paginator = QuestionActivityPagination()
        paginated_qs = paginator.paginate_queryset(activities, request, view=self)
        paginator._questions_today = stats["questions_today"]

        output = QuestionActivityOutputSerializer(paginated_qs, many=True)
        response = paginator.get_paginated_response(output.data)
        response.status_code = status.HTTP_200_OK
        return response
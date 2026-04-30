# qa/views.py
from django.http import StreamingHttpResponse
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from .selectors import question_activity_list, question_activity_stats
from .serializers import (
    AskQuestionInputSerializer,
    AskQuestionOutputSerializer,
    QuestionActivityOutputSerializer,
    QuestionActivityStatsSerializer,
    QuestionResultOutputSerializer,
    StreamQuestionInputSerializer,
)
from .services import (
    AskQuestionService,
    GetQuestionResultService,
    StreamQuestionService,
)


class QuestionAnsweringView(APIView):
    """
    POST /api/qa/ask/
    Submits a question to the async pipeline.
    Returns task_id immediately — client polls /result/<task_id>/.
    """

    def post(self, request):
        input_serializer = AskQuestionInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        result = AskQuestionService.execute(
            user=request.user,
            validated_data=input_serializer.validated_data,
        )

        return Response(AskQuestionOutputSerializer(result).data, status=202)


class QuestionResultView(APIView):
    """
    GET /api/qa/result/<task_id>/
    Polls the Celery result backend for a previously submitted question.
    Returns 202 while processing, 200 when complete.
    """

    def get(self, request, task_id: str):
        result = GetQuestionResultService.execute(task_id=task_id)
        http_status = 202 if result["status"] == "processing" else 200
        return Response(
            QuestionResultOutputSerializer(result).data,
            status=http_status,
        )


class ChatStreamView(APIView):
    """
    POST /api/qa/stream/
    Synchronous streaming path — returns NDJSON token stream.
    Embedding and retrieval errors are raised before the generator
    is entered so they surface as proper error responses, not mid-stream
    JSON error chunks.
    """

    def post(self, request):
        input_serializer = StreamQuestionInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)

        generator = StreamQuestionService.execute(
            user=request.user,
            validated_data=input_serializer.validated_data,
        )

        return StreamingHttpResponse(
            generator,
            content_type="application/x-ndjson",
        )


class QuestionActivityListView(APIView):
    """
    GET /api/qa/history/
    Paginated history of question activities for the authenticated user.
    Supports ?status= and ?document_id= filters via QuestionActivityFilter.
    Stats (total + today) are merged into the paginated response envelope.
    """

    def get(self, request):
        activities = question_activity_list(
            user=request.user,
            filters=request.query_params.dict(),
        )
        stats = question_activity_stats(user=request.user)

        paginator = PageNumberPagination()
        paginated_qs = paginator.paginate_queryset(activities, request, view=self)

        output = QuestionActivityOutputSerializer(paginated_qs, many=True)
        response_data = paginator.get_paginated_response(output.data).data

        # Merge stats into the DRF pagination envelope
        response_data.update(QuestionActivityStatsSerializer(stats).data)

        return Response(response_data, status=200)
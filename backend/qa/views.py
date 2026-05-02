from __future__ import annotations

from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from .pagination import QuestionActivityPagination
from .selectors import question_activity_list, question_activity_stats
from .serializers import (
    AskQuestionInputSerializer,
    AskQuestionOutputSerializer,
    QuestionActivityOutputSerializer,
    QuestionResultOutputSerializer,
    StreamQuestionInputSerializer,
)
from .services import (
    AskQuestionService,
    GetQuestionResultService,
    StreamQuestionService,
)


class QuestionAnsweringView(APIView):
    permission_classes = [IsAuthenticated]
    def post(self, request):
        input_serializer = AskQuestionInputSerializer(data=request.data)
        input_serializer.is_valid(raise_exception=True)
        result = AskQuestionService.execute(
            user=request.user,
            validated_data=input_serializer.validated_data,
        )
        return Response(
            AskQuestionOutputSerializer(result).data,
            status=status.HTTP_202_ACCEPTED,
        )


class QuestionResultView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request, task_id):  # receives uuid.UUID object from router
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
            status=status.HTTP_200_OK,
        )


class QuestionActivityListView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        activities = question_activity_list(
            user=request.user,
            filters=request.query_params.dict(),
        )
        stats = question_activity_stats(user=request.user)

        paginator = QuestionActivityPagination()
        paginated_qs = paginator.paginate_queryset(activities, request, view=self)
        paginator._questions_today = stats["questions_today"]

        output = QuestionActivityOutputSerializer(paginated_qs, many=True)
        response = paginator.get_paginated_response(output.data)
        response.status_code = status.HTTP_200_OK
        return response
from __future__ import annotations

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class QuestionActivityPagination(PageNumberPagination):
    """
    Custom paginator for GET /api/qa/history/ and /api/qa/activity/.

    Produces the envelope:
        {
            "total_questions": <count of filtered queryset>,
            "questions_today": <today's activity count, user-scoped>,
            "page":            <current page number>,
            "page_size":       <effective page size>,
            "total_pages":     <total page count>,
            "activities":      [...]
        }

    page_size_query_param enables ?page_size=N overrides per request.
    """

    page_size_query_param = "page_size"

    def get_paginated_response(self, data: list) -> Response:
        return Response(
            {
                "total_questions": self.page.paginator.count,
                "questions_today": getattr(self, "_questions_today", 0),
                "page": self.page.number,
                "page_size": self.get_page_size(self.request),
                "total_pages": self.page.paginator.num_pages,
                "activities": data,
            }
        )
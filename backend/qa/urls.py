# qa/urls.py
from django.urls import path

from .views import (
    ChatStreamView,
    QuestionAnsweringView,
    QuestionActivityListView,
    QuestionResultView,
)

urlpatterns = [
    path("ask/", QuestionAnsweringView.as_view(), name="qa-ask"),
    path("result/<str:task_id>/", QuestionResultView.as_view(), name="qa-result"),
    path("stream/", ChatStreamView.as_view(), name="qa-stream"),
    path("history/", QuestionActivityListView.as_view(), name="qa-history"),
    # Backward-compatible alias — tests and any existing clients using /activity/ still work
    path("activity/", QuestionActivityListView.as_view(), name="qa-activity"),
]
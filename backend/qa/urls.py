from django.urls import path

from .views import (
    ChatStreamView,
    QuestionAnsweringView,
    QuestionActivityListView,
    QuestionResultView,
)

urlpatterns = [
    path("ask/", QuestionAnsweringView.as_view(), name="qa-ask"),
    path("results/<uuid:task_id>/", QuestionResultView.as_view(), name="qa-results"),
    path("stream/", ChatStreamView.as_view(), name="qa-stream"),
    path("history/", QuestionActivityListView.as_view(), name="qa-history"),
    path("activity/", QuestionActivityListView.as_view(), name="qa-activity"),
]
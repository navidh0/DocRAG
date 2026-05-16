from django.urls import path
from .views import (
    DocumentListCreateView,
    DocumentRetrieveDestroyView,
    DocumentStatusView,
)

urlpatterns = [
    path("", DocumentListCreateView.as_view(), name="document-list-create"),
    path("<uuid:id>/", DocumentRetrieveDestroyView.as_view(), name="document-retrieve-destroy"),
    path("<uuid:id>/status/", DocumentStatusView.as_view(), name="document-status"),
]
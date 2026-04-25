
from django.urls import path
from .views import (
    DocumentListCreateView,
    DocumentRetrieveDestroyView, 
    DocumentStatusView, 
    DocumentChunksDebugView,
)

urlpatterns = [
    path('', DocumentListCreateView.as_view(), name='document-list-create'),
    path('<uuid:id>/', DocumentRetrieveDestroyView.as_view(), name='document-detail'),
    path('<uuid:id>/status/', DocumentStatusView.as_view(), name='document-status'),
    path('<uuid:id>/chunks/', DocumentChunksDebugView.as_view(), name='document-chunks-debug'),
]
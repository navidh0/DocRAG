from django.urls import path
from .views import QuestionAnsweringView, ChatStreamView, QuestionActivityListView

urlpatterns = [
    path('ask/', QuestionAnsweringView.as_view(), name='question-answering'),
    path('stream/', ChatStreamView.as_view(), name='chat-stream'),
    path('activity/', QuestionActivityListView.as_view(), name='question-activity'),
]
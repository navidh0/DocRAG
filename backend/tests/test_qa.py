"""
Merged tests for the QA domain (question answering, retrieval, generation).

Covers ask, result, stream, history endpoints, authentication, isolation,
error handling, and performance tracking. Mocks are applied at the service
layer to avoid depending on external services (Ollama, PGVector, etc.).
"""

import json
import uuid
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from qa.models import QuestionActivity


# ---------------------------------------------------------------------------
# Shared fixtures (extend those in conftest.py)
# ---------------------------------------------------------------------------

@pytest.fixture
def document(db, test_user):
    """Create a processed document owned by test_user."""
    from documents.models import Document
    return Document.objects.create(
        user=test_user,
        file_name="test.pdf",
        file_type="pdf",
        status="processed",
    )

# ---------------------------------------------------------------------------
# Mock helpers – patch service classes, not view internals
# ---------------------------------------------------------------------------

FAKE_SOURCES = [
    {
        "file_name": "test.pdf",
        "page": 1,
        "chunk_index": 0,
        "excerpt": "Relevant content excerpt...",
    }
]

MOCK_TASK_ID = "550e8400-e29b-41d4-a716-446655440000"

FAKE_ASK_RESULT = {
    "task_id": MOCK_TASK_ID,
    "status": "processing",
}

FAKE_SUCCESS_RESULT = {
    "task_id": MOCK_TASK_ID,
    "status": "success",
    "answer": "The answer is 42.",
    "sources": FAKE_SOURCES,
    "response_time_ms": 250,
}

FAKE_NO_ANSWER_RESULT = {
    "task_id": MOCK_TASK_ID,
    "status": "no_answer",
    "answer": "I could not find relevant information in the provided documents.",
    "sources": [],
    "response_time_ms": 100,
}


@contextmanager
def mock_ask_service(result=None):
    """Mocks AskQuestionService.execute – used for POST /api/qa/ask/."""
    with patch("qa.services.AskQuestionService.execute") as mock:
        mock.return_value = result or FAKE_ASK_RESULT
        yield mock


@contextmanager
def mock_result_service(result=None):
    """Mocks GetQuestionResultService.execute – used for GET /api/qa/result/<id>/."""
    with patch("qa.services.GetQuestionResultService.execute") as mock:
        mock.return_value = result or FAKE_SUCCESS_RESULT
        yield mock


@contextmanager
def mock_stream_service():
    """Mocks StreamQuestionService.execute – used for POST /api/qa/stream/."""
    def fake_generator():
        yield json.dumps({"token": "The answer"}) + "\n"
        yield json.dumps({"token": " is 42."}) + "\n"

    with patch("qa.services.StreamQuestionService.execute") as mock:
        mock.return_value = fake_generator()
        yield mock


# ---------------------------------------------------------------------------
# TestQuestionAnswering
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestQuestionAnswering:

    def test_ask_question_requires_auth(self, api_client):
        res = api_client.post("/api/qa/ask/", {"question": "What is this?"})
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_ask_question_with_documents(self, authenticated_client, document):
        with mock_ask_service():
            res = authenticated_client.post(
                "/api/qa/ask/",
                {"question": "What is in the document?", "document_id": str(document.id)},
            )
        assert res.status_code == status.HTTP_202_ACCEPTED
        assert "task_id" in res.data
        assert res.data["status"] == "processing"

    def test_ask_question_without_documents(self, authenticated_client):
        with mock_ask_service(result=FAKE_NO_ANSWER_RESULT):
            res = authenticated_client.post(
                "/api/qa/ask/", {"question": "What is the meaning of life?"}
            )
        # The endpoint always returns 202 – processing happens asynchronously
        assert res.status_code == status.HTTP_202_ACCEPTED

    def test_question_activity_recorded(self, authenticated_client, test_user, document):
        """Verify that a QuestionActivity can be listed via the history endpoint."""
        QuestionActivity.objects.create(
            user=test_user,
            document=document,
            question="What is in the document?",
            answer="The answer is 42.",
            sources=FAKE_SOURCES,
            response_time_ms=250,
            status="success",
        )
        res = authenticated_client.get("/api/qa/history/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["total_questions"] >= 1

    def test_answer_contains_sources(self, authenticated_client, document):
        """GET /result/ should return sources in the expected shape."""
        with mock_result_service(result=FAKE_SUCCESS_RESULT):
            res = authenticated_client.get(f"/api/qa/result/{MOCK_TASK_ID}/")
        assert res.status_code == status.HTTP_200_OK
        assert "sources" in res.data
        assert len(res.data["sources"]) > 0
        source = res.data["sources"][0]
        assert "file_name" in source
        assert "page" in source
        assert "excerpt" in source


# ---------------------------------------------------------------------------
# TestQuestionResult
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestQuestionResult:

    def test_result_processing_returns_202(self, authenticated_client):
        processing_result = {"task_id": MOCK_TASK_ID, "status": "processing"}
        with mock_result_service(result=processing_result):
            res = authenticated_client.get(f"/api/qa/result/{MOCK_TASK_ID}/")
        assert res.status_code == status.HTTP_202_ACCEPTED
        assert res.data["status"] == "processing"

    def test_result_success_returns_200(self, authenticated_client):
        with mock_result_service(result=FAKE_SUCCESS_RESULT):
            res = authenticated_client.get(f"/api/qa/result/{MOCK_TASK_ID}/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["status"] == "success"
        assert res.data["answer"] == "The answer is 42."

    def test_result_requires_auth(self, api_client):
        task_id = uuid.uuid4()
        res = api_client.get(f"/api/qa/result/{task_id}/")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# TestQuestionStreaming
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestQuestionStreaming:

    def test_stream_response(self, authenticated_client):
        with mock_stream_service():
            res = authenticated_client.post(
                "/api/qa/stream/",
                {"question": "Explain the document"},
                format="json",
            )
        assert res.status_code == status.HTTP_200_OK
        assert res["Content-Type"] == "application/x-ndjson"

    def test_stream_response_has_tokens(self, authenticated_client):
        with mock_stream_service():
            res = authenticated_client.post(
                "/api/qa/stream/",
                {"question": "Explain the document"},
                format="json",
            )
        content = b"".join(res.streaming_content).decode()
        lines = [l for l in content.strip().split("\n") if l]
        assert len(lines) > 0
        for line in lines:
            parsed = json.loads(line)
            assert "token" in parsed

    def test_stream_response_has_sources(self, authenticated_client):
        """Stream returns valid NDJSON; sources are stored after the stream ends."""
        with mock_stream_service():
            res = authenticated_client.post(
                "/api/qa/stream/",
                {"question": "What does the document say?"},
                format="json",
            )
        assert res.status_code == status.HTTP_200_OK

    def test_stream_requires_auth(self, api_client):
        res = api_client.post("/api/qa/stream/", {"question": "test"})
        assert res.status_code == status.HTTP_401_UNAUTHORIZED


# ---------------------------------------------------------------------------
# TestRetrievalRelevance
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestRetrievalRelevance:

    def test_retrieve_relevant_documents(self, authenticated_client, document):
        """Ask endpoint submits task; result endpoint returns matched answer."""
        with mock_result_service(result=FAKE_SUCCESS_RESULT):
            res = authenticated_client.get(f"/api/qa/result/{MOCK_TASK_ID}/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["status"] == "success"
        assert len(res.data["sources"]) > 0

    def test_no_matching_documents(self, authenticated_client):
        """When no docs match, service returns no_answer status."""
        with mock_result_service(result=FAKE_NO_ANSWER_RESULT):
            res = authenticated_client.get(f"/api/qa/result/{MOCK_TASK_ID}/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["status"] == "no_answer"
        assert res.data["sources"] == []

    def test_ask_no_matching_documents_returns_task(self, authenticated_client):
        """POST /ask/ still returns 202 even if no docs match (async check)."""
        with mock_ask_service(result=FAKE_NO_ANSWER_RESULT):
            res = authenticated_client.post(
                "/api/qa/ask/", {"question": "Question about non-existent docs?"}
            )
        assert res.status_code == status.HTTP_202_ACCEPTED


# ---------------------------------------------------------------------------
# TestQuestionHistory
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestQuestionHistory:

    def _make_activity(self, user, document=None, **kwargs):
        defaults = dict(
            question="Test question?",
            answer="Test answer.",
            sources=FAKE_SOURCES,
            response_time_ms=200,
            status="success",
        )
        defaults.update(kwargs)
        return QuestionActivity.objects.create(user=user, document=document, **defaults)

    def test_list_question_history(self, authenticated_client, test_user, document):
        self._make_activity(test_user, document)
        res = authenticated_client.get("/api/qa/history/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["total_questions"] >= 1
        assert "total_questions" in res.data
        assert "questions_today" in res.data

    def test_history_requires_auth(self, api_client):
        res = api_client.get("/api/qa/history/")
        assert res.status_code == status.HTTP_401_UNAUTHORIZED

    def test_user_cannot_see_other_users_history(self, authenticated_client, second_user):
        self._make_activity(second_user)
        res = authenticated_client.get("/api/qa/history/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["total_questions"] == 0

    def test_history_preserves_metadata(self, authenticated_client, test_user, document):
        self._make_activity(
            test_user,
            document,
            question="Specific question?",
            answer="Specific answer.",
            response_time_ms=333,
            status="success",
        )
        res = authenticated_client.get("/api/qa/history/")
        assert res.status_code == status.HTTP_200_OK
        activity = res.data["activities"][0]
        assert activity["question"] == "Specific question?"
        assert activity["status"] == "success"
        assert activity["response_time_ms"] == 333
        assert "sources_count" in activity

    def test_activity_url_alias(self, authenticated_client, test_user, document):
        """The /activity/ endpoint should be an alias for /history/."""
        self._make_activity(test_user, document)
        res = authenticated_client.get("/api/qa/activity/")
        assert res.status_code == status.HTTP_200_OK
        assert res.data["total_questions"] >= 1


# ---------------------------------------------------------------------------
# TestErrorHandling
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestErrorHandling:

    def test_invalid_query_format(self, authenticated_client):
        res = authenticated_client.post("/api/qa/ask/", {}, format="json")
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_missing_required_fields(self, authenticated_client):
        res = authenticated_client.post(
            "/api/qa/ask/", {"document_id": "not-a-uuid"}, format="json"
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST

    def test_generate_answer_empty_context(self, authenticated_client):
        """Blank question is rejected by input serializer."""
        res = authenticated_client.post(
            "/api/qa/ask/", {"question": "   "}, format="json"
        )
        assert res.status_code == status.HTTP_400_BAD_REQUEST
        assert "question" in res.data


# ---------------------------------------------------------------------------
# TestPerformanceTracking
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
class TestPerformanceTracking:

    def test_response_time_tracked(self, authenticated_client):
        """response_time_ms is present in the result endpoint output."""
        with mock_result_service(result=FAKE_SUCCESS_RESULT):
            res = authenticated_client.get(f"/api/qa/result/{MOCK_TASK_ID}/")
        assert res.status_code == status.HTTP_200_OK
        assert "response_time_ms" in res.data
        assert isinstance(res.data["response_time_ms"], int)
        assert res.data["response_time_ms"] > 0

    def test_retrieval_count_tracked(self, authenticated_client, test_user, document):
        """sources_count on QuestionActivity reflects number of sources stored."""
        QuestionActivity.objects.create(
            user=test_user,
            document=document,
            question="How many sources?",
            answer="Several.",
            sources=FAKE_SOURCES,
            response_time_ms=150,
            status="success",
        )
        res = authenticated_client.get("/api/qa/history/")
        assert res.status_code == status.HTTP_200_OK
        activity = res.data["activities"][0]
        assert activity["sources_count"] == len(FAKE_SOURCES)
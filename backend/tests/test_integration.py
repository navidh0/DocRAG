# tests/test_integration.py

import pytest
import uuid
from rest_framework import status
from rest_framework.test import APIClient
from io import BytesIO
from unittest.mock import patch, MagicMock
from django.contrib.auth import get_user_model
from langchain_core.documents import Document

pytestmark = pytest.mark.django_db
User = get_user_model()


def get_response_results(data):
    if isinstance(data, dict):
        return data.get('results', data.get('activities', []))
    return data


def generate_unique_username(base="user"):
    return f"{base}_{uuid.uuid4().hex[:8]}"


def mock_qa_dependencies():
    """
    Returns a context manager stack that mocks all external dependencies
    in the QA view: ollama.Client, PGVector, and rerank_with_gemma4.
    """
    import contextlib

    fake_doc = Document(
        page_content="Machine learning is a subset of AI.",
        metadata={
            "user_id": "1",
            "document_id": "test-doc",
            "file_name": "test.txt",
            "page": 1,
            "chunk_index": 0,
        }
    )

    @contextlib.contextmanager
    def _stack():
        with patch('ollama.Client') as mock_client_class, \
             patch('qa.views.PGVector') as mock_pgvector_class, \
             patch('qa.views.rerank_with_gemma4') as mock_rerank:

            # Mock ollama
            mock_ollama = mock_client_class.return_value
            mock_ollama.embed.return_value = {'embeddings': [[0.1] * 768]}
            mock_ollama.generate.return_value = {'response': 'Mocked answer'}

            # Mock PGVector store
            mock_store = mock_pgvector_class.return_value
            mock_store.similarity_search_by_vector.return_value = [fake_doc]

            # Mock reranker — just return the docs as-is
            mock_rerank.return_value = [fake_doc]

            yield mock_ollama

    return _stack()


@pytest.mark.integration
class TestEndToEndWorkflow:
    def test_workflow_document_then_activity(self, authenticated_client, test_document_text):
        client = authenticated_client

        file = BytesIO(test_document_text.encode())
        file.name = 'history_doc.txt'
        doc_resp = client.post('/api/documents/', {'file': file}, format='multipart')
        assert doc_resp.status_code == status.HTTP_201_CREATED
        doc_id = doc_resp.data['id']

        questions = ['First question?', 'Second question?', 'Third question?']

        with mock_qa_dependencies():
            for q in questions:
                resp = client.post(
                    '/api/qa/ask/',
                    {'question': q, 'document_id': doc_id},
                    format='json'
                )
                assert resp.status_code == status.HTTP_200_OK, \
                    f"QA ask failed for '{q}': {resp.data}"

        history_resp = client.get('/api/qa/activity/')
        assert history_resp.status_code == status.HTTP_200_OK

        activities = get_response_results(history_resp.data)
        recorded_questions = [h['question'] for h in activities]

        for q in questions:
            assert q in recorded_questions, \
                f"Question '{q}' not found in activity. Got: {recorded_questions}"


@pytest.mark.integration
class TestConcurrentOperations:
    def test_multiple_documents_uploaded_simultaneously(self, authenticated_client, test_document_text):
        client = authenticated_client
        doc_ids = []

        for i in range(3):
            file = BytesIO(test_document_text.encode())
            file.name = f'concurrent_{i}.txt'
            resp = client.post('/api/documents/', {'file': file}, format='multipart')
            assert resp.status_code == status.HTTP_201_CREATED
            doc_ids.append(resp.data['id'])

        docs_resp = client.get('/api/documents/')
        uploaded_docs = get_response_results(docs_resp.data)
        uploaded_ids = [d['id'] for d in uploaded_docs]

        for doc_id in doc_ids:
            assert doc_id in uploaded_ids

    def test_rapid_question_asking(self, authenticated_client, test_document_text):
        client = authenticated_client
        file = BytesIO(test_document_text.encode())
        file.name = 'rapid_doc.txt'
        doc_resp = client.post('/api/documents/', {'file': file}, format='multipart')
        assert doc_resp.status_code == status.HTTP_201_CREATED
        doc_id = doc_resp.data['id']

        with mock_qa_dependencies():
            for i in range(3):
                resp = client.post(
                    '/api/qa/ask/',
                    {'question': f'Rapid question {i}?', 'document_id': doc_id},
                    format='json'
                )
                assert resp.status_code == status.HTTP_200_OK, \
                    f"QA ask failed for question {i}: {resp.data}"

        activity_resp = client.get('/api/qa/activity/')
        assert activity_resp.status_code == status.HTTP_200_OK

        activities = get_response_results(activity_resp.data)
        questions = [h['question'] for h in activities]

        for i in range(3):
            assert f'Rapid question {i}?' in questions, \
                f"'Rapid question {i}?' not found. Got: {questions}"


@pytest.mark.integration
class TestDataPersistence:
    def test_question_activity_survives_logout_login(self, test_document_text):
        from rest_framework_simplejwt.tokens import RefreshToken

        uname = generate_unique_username("persist")
        user = User.objects.create_user(
            username=uname, password='Pass123!', email=f"{uname}@test.com"
        )

        client = APIClient()
        token = str(RefreshToken.for_user(user).access_token)
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

        file = BytesIO(test_document_text.encode())
        file.name = 'persist_hist.txt'
        doc_resp = client.post('/api/documents/', {'file': file}, format='multipart')
        assert doc_resp.status_code == status.HTTP_201_CREATED
        doc_id = doc_resp.data['id']

        with mock_qa_dependencies():
            resp = client.post(
                '/api/qa/ask/',
                {'question': 'Persistent question?', 'document_id': doc_id},
                format='json'
            )
            assert resp.status_code == status.HTTP_200_OK, \
                f"QA ask failed: {resp.data}"

        # Simulate new session with fresh token
        client_new = APIClient()
        new_token = str(RefreshToken.for_user(user).access_token)
        client_new.credentials(HTTP_AUTHORIZATION=f'Bearer {new_token}')

        activity_resp = client_new.get('/api/qa/activity/')
        assert activity_resp.status_code == status.HTTP_200_OK

        activities = get_response_results(activity_resp.data)
        questions = [h['question'] for h in activities]

        assert 'Persistent question?' in questions, \
            f"Persistent question not found after re-login. Got: {questions}"
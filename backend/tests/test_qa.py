"""Tests for the QA domain (question answering, retrieval, generation)."""
import pytest
from rest_framework import status
from rest_framework.test import APIClient
from io import BytesIO
from unittest.mock import patch, MagicMock
from langchain_core.documents import Document as LangchainDocument
from qa.models import QuestionActivity

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

def make_fake_doc(user_id="1", doc_id="test-doc"):
    return LangchainDocument(
        page_content="Machine learning is a subset of AI.",
        metadata={
            "user_id": str(user_id),
            "document_id": str(doc_id),
            "file_name": "test.txt",
            "page": 1,
            "chunk_index": 0,
        }
    )


def qa_mocks(user_id="1", doc_id="test-doc"):
    """
    Context manager that patches all three external dependencies used by
    QuestionAnsweringView: ollama.Client, PGVector, and rerank_with_gemma4.
    """
    import contextlib

    @contextlib.contextmanager
    def _stack():
        fake_doc = make_fake_doc(user_id, doc_id)
        with patch('qa.views.ollama.Client') as mock_ollama_cls, \
             patch('qa.views.PGVector') as mock_pgvector_cls, \
             patch('qa.views.rerank_with_gemma4') as mock_rerank:

            mock_ollama = mock_ollama_cls.return_value
            mock_ollama.embed.return_value = {'embeddings': [[0.1] * 768]}
            mock_ollama.generate.return_value = {'response': 'Mocked answer'}

            mock_store = mock_pgvector_cls.return_value
            mock_store.similarity_search_by_vector.return_value = [fake_doc]

            mock_rerank.return_value = [fake_doc]

            yield mock_ollama

    return _stack()


# ---------------------------------------------------------------------------
# TestQuestionAnswering
# ---------------------------------------------------------------------------

@pytest.mark.qa
class TestQuestionAnswering:

    def test_ask_question_with_documents(self, authenticated_client, test_document_text):
        file = BytesIO(test_document_text.encode())
        file.name = 'context.txt'
        doc_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        doc_id = doc_resp.data['id']

        with qa_mocks(doc_id=doc_id):
            response = authenticated_client.post(
                '/api/qa/ask/',
                {'question': 'What is the meaning of life?', 'document_id': doc_id},
                format='json'
            )

        assert response.status_code == status.HTTP_200_OK
        assert 'answer' in response.data
        assert 'sources' in response.data

    def test_ask_question_requires_auth(self, api_client):
        response = api_client.post(
            '/api/qa/ask/',
            {'question': 'Who am I?'},
            format='json'
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_ask_question_without_documents(self, authenticated_client):
        """When no docs match, the view returns a no_answer response — that's valid."""
        with patch('qa.views.ollama.Client') as mock_ollama_cls, \
             patch('qa.views.PGVector') as mock_pgvector_cls:

            mock_ollama_cls.return_value.embed.return_value = {'embeddings': [[0.1] * 768]}
            mock_pgvector_cls.return_value.similarity_search_by_vector.return_value = []

            response = authenticated_client.post(
                '/api/qa/ask/',
                {'question': 'What is 2+2?'},
                format='json'
            )

        assert response.status_code == status.HTTP_200_OK
        assert 'answer' in response.data

    def test_question_activity_recorded(self, authenticated_client, test_document_text):
        file = BytesIO(test_document_text.encode())
        file.name = 'doc.txt'
        doc_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        doc_id = doc_resp.data['id']

        with qa_mocks(doc_id=doc_id):
            resp = authenticated_client.post(
                '/api/qa/ask/',
                {'question': 'Test question?', 'document_id': doc_id},
                format='json'
            )
            assert resp.status_code == status.HTTP_200_OK, f"QA ask failed: {resp.data}"

        # Activity must exist regardless of status
        assert QuestionActivity.objects.filter(question='Test question?').exists()

    def test_answer_contains_sources(self, authenticated_client, test_document_text):
        file = BytesIO(test_document_text.encode())
        file.name = 'reference.txt'
        doc_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        doc_id = doc_resp.data['id']

        with qa_mocks(doc_id=doc_id):
            response = authenticated_client.post(
                '/api/qa/ask/',
                {'question': 'Where did this come from?', 'document_id': doc_id},
                format='json'
            )

        assert 'sources' in response.data
        assert isinstance(response.data['sources'], list)


# ---------------------------------------------------------------------------
# TestQuestionStreaming
# ---------------------------------------------------------------------------

@pytest.mark.qa
class TestQuestionStreaming:

    def test_stream_response(self, authenticated_client, test_document_text):
        file = BytesIO(test_document_text.encode())
        file.name = 'doc.txt'
        doc_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        doc_id = doc_resp.data['id']

        with patch('qa.views.StreamOptimizer') as mock_optimizer_cls, \
             patch('qa.views.rerank_with_gemma4') as mock_rerank:

            fake_doc = make_fake_doc(doc_id=doc_id)
            mock_opt = mock_optimizer_cls.return_value
            mock_opt.get_query_embedding.return_value = [0.1] * 768
            mock_opt.retrieve_documents.return_value = [fake_doc]
            mock_opt.extract_sources.return_value = []
            mock_opt.stream_response_buffered.return_value = iter([
                '{"token": "Hello"}\n',
                '{"token": " world"}\n',
            ])
            mock_rerank.return_value = [fake_doc]

            response = authenticated_client.post(
                '/api/qa/stream/',
                {'question': 'Stream this?', 'document_id': doc_id},
                format='json'
            )

        assert response.status_code in [status.HTTP_200_OK, status.HTTP_206_PARTIAL_CONTENT]

    def test_stream_response_has_sources(self, authenticated_client, test_document_text):
        file = BytesIO(test_document_text.encode())
        file.name = 'source.txt'
        doc_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        doc_id = doc_resp.data['id']

        with patch('qa.views.StreamOptimizer') as mock_optimizer_cls, \
             patch('qa.views.rerank_with_gemma4') as mock_rerank:

            fake_doc = make_fake_doc(doc_id=doc_id)
            mock_opt = mock_optimizer_cls.return_value
            mock_opt.get_query_embedding.return_value = [0.1] * 768
            mock_opt.retrieve_documents.return_value = [fake_doc]
            mock_opt.extract_sources.return_value = []
            mock_opt.stream_response_buffered.return_value = iter([
                '{"token": "Streaming"}\n',
            ])
            mock_rerank.return_value = [fake_doc]

            response = authenticated_client.post(
                '/api/qa/stream/',
                {'question': 'With sources?', 'document_id': doc_id},
                format='json'
            )

        assert response.status_code in [status.HTTP_200_OK, status.HTTP_206_PARTIAL_CONTENT]


# ---------------------------------------------------------------------------
# TestRetrievalRelevance
# ---------------------------------------------------------------------------

@pytest.mark.qa
class TestRetrievalRelevance:

    def test_retrieve_relevant_documents(self, authenticated_client, test_document_text):
        doc_ids = []
        for name in ['relevant.txt', 'other.txt']:
            file = BytesIO(test_document_text.encode())
            file.name = name
            doc_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
            doc_ids.append(doc_resp.data['id'])

        with qa_mocks():
            response = authenticated_client.post(
                '/api/qa/ask/',
                {'question': 'Question?', 'document_id': doc_ids[0]},
                format='json'
            )

        assert response.status_code == status.HTTP_200_OK

    def test_no_matching_documents(self, authenticated_client):
        with patch('qa.views.ollama.Client') as mock_ollama_cls, \
             patch('qa.views.PGVector') as mock_pgvector_cls:

            mock_ollama_cls.return_value.embed.return_value = {'embeddings': [[0.1] * 768]}
            mock_pgvector_cls.return_value.similarity_search_by_vector.return_value = []

            response = authenticated_client.post(
                '/api/qa/ask/',
                {'question': 'Question about non-existent docs?'},
                format='json'
            )

        assert response.status_code == status.HTTP_200_OK


# ---------------------------------------------------------------------------
# TestQuestionHistory
# ---------------------------------------------------------------------------

@pytest.mark.qa
class TestQuestionHistory:

    def test_list_question_history(self, authenticated_client, test_document_text):
        file = BytesIO(test_document_text.encode())
        file.name = 'doc.txt'
        doc_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        doc_id = doc_resp.data['id']

        with qa_mocks(doc_id=doc_id):
            resp = authenticated_client.post(
                '/api/qa/ask/',
                {'question': 'Tracked question?', 'document_id': doc_id},
                format='json'
            )
            assert resp.status_code == status.HTTP_200_OK, f"Ask failed: {resp.data}"

        response = authenticated_client.get('/api/qa/activity/')
        assert response.status_code == status.HTTP_200_OK

        # The view serializes activities with key "question", not "query"
        activities = response.data.get('activities', response.data.get('results', []))
        questions = [q['question'] for q in activities]  # ← fixed: 'question' not 'query'
        assert 'Tracked question?' in questions, f"Got: {questions}"

    def test_history_requires_auth(self, api_client):
        response = api_client.get('/api/qa/activity/')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_user_cannot_see_other_users_history(self, authenticated_client, second_user, test_document_text):
        file = BytesIO(test_document_text.encode())
        file.name = 'doc.txt'
        doc_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        doc_id = doc_resp.data['id']

        with qa_mocks(doc_id=doc_id):
            authenticated_client.post(
                '/api/qa/ask/',
                {'question': 'Private question?', 'document_id': doc_id},
                format='json'
            )

        client2 = APIClient()
        from rest_framework_simplejwt.tokens import RefreshToken
        client2.credentials(HTTP_AUTHORIZATION=f'Bearer {str(RefreshToken.for_user(second_user).access_token)}')

        response = client2.get('/api/qa/activity/')
        activities = response.data.get('activities', response.data.get('results', []))
        questions = [q['question'] for q in activities]
        assert 'Private question?' not in questions

    def test_history_preserves_metadata(self, authenticated_client, test_document_text):
        file = BytesIO(test_document_text.encode())
        file.name = 'doc.txt'
        doc_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        doc_id = doc_resp.data['id']

        with qa_mocks(doc_id=doc_id):
            authenticated_client.post(
                '/api/qa/ask/',
                {'question': 'Metadata test?', 'document_id': doc_id},
                format='json'
            )

        response = authenticated_client.get('/api/qa/activity/')
        activities = response.data.get('activities', response.data.get('results', []))
        if activities:
            q = activities[0]
            assert 'created_at' in q
            assert 'status' in q


# ---------------------------------------------------------------------------
# TestErrorHandling
# ---------------------------------------------------------------------------

@pytest.mark.qa
class TestErrorHandling:

    def test_invalid_query_format(self, authenticated_client):
        response = authenticated_client.post(
            '/api/qa/ask/',
            {'invalid_field': 'bad'},
            format='json'
        )
        assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_422_UNPROCESSABLE_ENTITY]

    def test_missing_required_fields(self, authenticated_client):
        response = authenticated_client.post('/api/qa/ask/', {}, format='json')
        assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_422_UNPROCESSABLE_ENTITY]

    def test_generate_answer_empty_context(self, authenticated_client):
        with patch('qa.views.ollama.Client') as mock_ollama_cls, \
             patch('qa.views.PGVector') as mock_pgvector_cls:

            mock_ollama_cls.return_value.embed.return_value = {'embeddings': [[0.1] * 768]}
            mock_pgvector_cls.return_value.similarity_search_by_vector.return_value = []

            response = authenticated_client.post(
                '/api/qa/ask/',
                {'question': 'Query?'},
                format='json'
            )

        assert response.status_code in [status.HTTP_200_OK, status.HTTP_400_BAD_REQUEST]


# ---------------------------------------------------------------------------
# TestPerformanceTracking
# ---------------------------------------------------------------------------

@pytest.mark.qa
class TestPerformanceTracking:

    def test_response_time_tracked(self, authenticated_client, test_document_text):
        file = BytesIO(test_document_text.encode())
        file.name = 'doc.txt'
        doc_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        doc_id = doc_resp.data['id']

        with qa_mocks(doc_id=doc_id):
            response = authenticated_client.post(
                '/api/qa/ask/',
                {'question': 'Time test?', 'document_id': doc_id},
                format='json'
            )

        assert response.status_code == status.HTTP_200_OK
        assert 'response_time_ms' in response.data

    def test_retrieval_count_tracked(self, authenticated_client, test_document_text):
        file = BytesIO(test_document_text.encode())
        file.name = 'doc.txt'
        doc_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        doc_id = doc_resp.data['id']

        with qa_mocks(doc_id=doc_id):
            response = authenticated_client.post(
                '/api/qa/ask/',
                {'question': 'Retrieval test?', 'document_id': doc_id},
                format='json'
            )

        assert response.status_code == status.HTTP_200_OK
        assert 'sources' in response.data
import pytest
import os
import uuid
from django.utils.timezone import now
from datetime import timedelta
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from documents.models import Document
from qa.models import QuestionActivity

User = get_user_model()

def generate_unique_username(base="testuser"):
    return f"{base}_{uuid.uuid4().hex[:8]}"

@pytest.mark.django_db
class TestAuthentication:
    def test_register_user(self):
        client = APIClient()
        unique_username = generate_unique_username()
        res = client.post('/api/auth/register/', {
            "username": unique_username,
            "email": f"{unique_username}@test.com",
            "password": "SecurePass123!",
            "password_confirm": "SecurePass123!"
        })
        assert res.status_code == 201
        assert User.objects.filter(username=unique_username).exists()

    def test_login_user(self):
        client = APIClient()
        user = User.objects.create_user(username=generate_unique_username(), password="SecurePass123!")
        res = client.post('/api/auth/login/', {
            "username": user.username,
            "password": "SecurePass123!"
        })
        assert res.status_code == 200
        assert 'access' in res.data

    def test_logout_user(self):
        client = APIClient()
        user = User.objects.create_user(username=generate_unique_username(), password="SecurePass123!")
        
        login_res = client.post('/api/auth/login/', {
            "username": user.username,
            "password": "SecurePass123!"
        })
        assert login_res.status_code == 200

        access_token = login_res.data['access']
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')
        
        # refresh token is in cookie — client sends it automatically
        res = client.post('/api/auth/logout/')
        assert res.status_code == 200

    def test_me_endpoint(self):
        client = APIClient()
        user = User.objects.create_user(username=generate_unique_username(), password="SecurePass123!")
        login_res = client.post('/api/auth/login/', {
            "username": user.username,
            "password": "SecurePass123!"
        })
        token = login_res.data['access']
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        res = client.get('/api/auth/me/')
        assert res.status_code == 200
        assert res.data['username'] == user.username


@pytest.mark.django_db
class TestDocumentUpload:
    def setup_method(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username=generate_unique_username(), password="SecurePass123!")
        login_res = self.client.post('/api/auth/login/', {
            "username": self.user.username,
            "password": "SecurePass123!"
        })
        self.token = login_res.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    def test_upload_pdf_document(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        pdf_content = b"%PDF-1.4 fake pdf content"
        pdf_file = SimpleUploadedFile("test.pdf", pdf_content, content_type="application/pdf")
        res = self.client.post('/api/documents/', {'file': pdf_file}, format='multipart')
        assert res.status_code == 201
        assert Document.objects.filter(file_name="test.pdf").exists()

    def test_upload_excel_document(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        excel_content = b"fake excel content"
        excel_file = SimpleUploadedFile("test.xlsx", excel_content, content_type="application/vnd.ms-excel")
        res = self.client.post('/api/documents/', {'file': excel_file}, format='multipart')
        assert res.status_code == 201
        doc = Document.objects.get(file_name="test.xlsx")
        assert doc.file_type == "xlsx"

    def test_document_belongs_to_user(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        pdf_file = SimpleUploadedFile("test.pdf", b"%PDF-1.4", content_type="application/pdf")
        self.client.post('/api/documents/', {'file': pdf_file}, format='multipart')
        doc = Document.objects.get(file_name="test.pdf")
        assert doc.user.id == self.user.id


@pytest.mark.django_db
class TestDocumentListing:
    def setup_method(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username=generate_unique_username(), password="SecurePass123!")
        self.other_user = User.objects.create_user(username=generate_unique_username("otheruser"), password="SecurePass123!")
        
        login_res = self.client.post('/api/auth/login/', {
            "username": self.user.username,
            "password": "SecurePass123!"
        })
        self.token = login_res.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    def test_list_own_documents(self):
        Document.objects.create(user=self.user, file_name="doc1.pdf", file_type="pdf", status="completed")
        Document.objects.create(user=self.user, file_name="doc2.xlsx", file_type="xlsx", status="completed")
        res = self.client.get('/api/documents/')
        assert res.status_code == 200
        assert len(res.data['results']) == 2

    def test_cannot_list_other_users_documents(self):
        Document.objects.create(user=self.user, file_name="my_doc.pdf", file_type="pdf", status="completed")
        Document.objects.create(user=self.other_user, file_name="other_doc.pdf", file_type="pdf", status="completed")
        res = self.client.get('/api/documents/')
        assert res.status_code == 200
        assert len(res.data['results']) == 1
        assert res.data['results'][0]['file_name'] == "my_doc.pdf"

    def test_filter_by_file_type(self):
        Document.objects.create(user=self.user, file_name="doc1.pdf", file_type="pdf", status="completed")
        Document.objects.create(user=self.user, file_name="doc2.xlsx", file_type="xlsx", status="completed")
        res = self.client.get('/api/documents/?file_type=pdf')
        assert res.status_code == 200
        assert len(res.data['results']) == 1
        assert res.data['results'][0]['file_type'] == "pdf"

    def test_search_by_file_name(self):
        Document.objects.create(user=self.user, file_name="annual_report.pdf", file_type="pdf", status="completed")
        Document.objects.create(user=self.user, file_name="budget.xlsx", file_type="xlsx", status="completed")
        res = self.client.get('/api/documents/?search=annual')
        assert res.status_code == 200
        assert len(res.data['results']) == 1
        assert "annual_report" in res.data['results'][0]['file_name']

    def test_ordering_by_date(self):
        old_doc = Document.objects.create(
            user=self.user,
            file_name="old.pdf",
            file_type="pdf",
            status="completed",
            created_at=now() - timedelta(seconds=10),
        )

        new_doc = Document.objects.create(
            user=self.user,
            file_name="new.pdf",
            file_type="pdf",
            status="completed",
            created_at=now(),
        )

        res = self.client.get('/api/documents/?ordering=-created_at')

        assert res.status_code == 200

        results = res.data['results']
        filenames = [doc['file_name'] for doc in results]

        assert filenames == ["new.pdf", "old.pdf"]


@pytest.mark.django_db
class TestDocumentDetail:
    def setup_method(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username=generate_unique_username(), password="SecurePass123!")
        self.other_user = User.objects.create_user(username=generate_unique_username("otheruser"), password="SecurePass123!")
        
        login_res = self.client.post('/api/auth/login/', {
            "username": self.user.username,
            "password": "SecurePass123!"
        })
        self.token = login_res.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    def test_retrieve_document(self):
        doc = Document.objects.create(user=self.user, file_name="doc.pdf", file_type="pdf", status="completed")
        res = self.client.get(f'/api/documents/{doc.id}/')
        assert res.status_code == 200
        assert res.data['file_name'] == "doc.pdf"

    def test_cannot_retrieve_other_users_document(self):
        doc = Document.objects.create(user=self.other_user, file_name="doc.pdf", file_type="pdf", status="completed")
        res = self.client.get(f'/api/documents/{doc.id}/')
        assert res.status_code == 404

    def test_delete_document(self):
        doc = Document.objects.create(user=self.user, file_name="doc.pdf", file_type="pdf", status="completed")
        res = self.client.delete(f'/api/documents/{doc.id}/')
        assert res.status_code == 200
        assert not Document.objects.filter(id=doc.id).exists()


@pytest.mark.django_db
class TestUserIsolation:
    def test_user_cannot_access_other_users_documents(self):
        user1 = User.objects.create_user(username=generate_unique_username("user1"), password="Pass123!")
        user2 = User.objects.create_user(username=generate_unique_username("user2"), password="Pass123!")
        
        Document.objects.create(user=user1, file_name="user1_doc.pdf", file_type="pdf", status="completed")
        Document.objects.create(user=user2, file_name="user2_doc.pdf", file_type="pdf", status="completed")
        
        client = APIClient()
        login_res = client.post('/api/auth/login/', {
            "username": user1.username,
            "password": "Pass123!"
        })
        token = login_res.data['access']
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        
        res = client.get('/api/documents/')
        assert len(res.data['results']) == 1
        assert res.data['results'][0]['file_name'] == "user1_doc.pdf"


@pytest.mark.django_db
class TestQuestionAnswering:
    def setup_method(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username=generate_unique_username(), password="SecurePass123!")
        
        login_res = self.client.post('/api/auth/login/', {
            "username": self.user.username,
            "password": "SecurePass123!"
        })
        self.token = login_res.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    def test_question_requires_authentication(self):
        client = APIClient()
        res = client.post('/api/qa/ask/', {'question': 'What is AI?'})
        assert res.status_code == 401

    def test_question_requires_question_text(self):
        res = self.client.post('/api/qa/ask/', {'question': ''})
        assert res.status_code == 400

    def test_activity_tracking_created_on_question(self):
        question = QuestionActivity.objects.create(
            user=self.user,
            question="What is this?",
            answer="This is an answer",
            sources=[{"file": "test.pdf", "page": 1}],
            response_time_ms=500,
            status="success"
        )
        assert question.user.id == self.user.id
        assert question.question == "What is this?"


@pytest.mark.django_db
class TestActivityTracking:
    def setup_method(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username=generate_unique_username(), password="SecurePass123!")
        
        login_res = self.client.post('/api/auth/login/', {
            "username": self.user.username,
            "password": "SecurePass123!"
        })
        self.token = login_res.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token}')

    def test_list_user_activity(self):
        QuestionActivity.objects.create(user=self.user, question="Q1", answer="A1", sources=[], response_time_ms=100, status="success")
        QuestionActivity.objects.create(user=self.user, question="Q2", answer="A2", sources=[], response_time_ms=200, status="success")
        res = self.client.get('/api/qa/activity/')
        assert res.status_code == 200
        assert res.data['total_questions'] == 2

    def test_activity_filtering_by_status(self):
        QuestionActivity.objects.create(user=self.user, question="Q1", answer="A1", sources=[], response_time_ms=100, status="success")
        QuestionActivity.objects.create(user=self.user, question="Q2", answer="A2", sources=[], response_time_ms=200, status="error")
        res = self.client.get('/api/qa/activity/?status=success')
        assert res.status_code == 200
        assert res.data['total_questions'] == 1

    def test_activity_pagination(self):
        for i in range(25):
            QuestionActivity.objects.create(user=self.user, question=f"Q{i}", answer=f"A{i}", sources=[], response_time_ms=100, status="success")
        res = self.client.get('/api/qa/activity/?page=1&page_size=20')
        assert res.status_code == 200
        assert len(res.data['activities']) == 20
        assert res.data['total_pages'] == 2

    def test_cannot_see_other_users_activity(self):
        other_user = User.objects.create_user(username=generate_unique_username("otheruser"), password="SecurePass123!")
        QuestionActivity.objects.create(user=self.user, question="My Q", answer="My A", sources=[], response_time_ms=100, status="success")
        QuestionActivity.objects.create(user=other_user, question="Other Q", answer="Other A", sources=[], response_time_ms=100, status="success")
        res = self.client.get('/api/qa/activity/')
        assert res.status_code == 200
        assert res.data['total_questions'] == 1


# Corrected Shared Fixtures
@pytest.fixture
def authenticated_user(db):
    user = User.objects.create_user(username=generate_unique_username(), password="SecurePass123!")
    return user

@pytest.fixture
def authenticated_client(db):
    user = User.objects.create_user(username=generate_unique_username(), password="SecurePass123!")
    client = APIClient()
    login_res = client.post('/api/auth/login/', {
        "username": user.username,
        "password": "SecurePass123!"
    })
    token = login_res.data['access']
    client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
    return client, user
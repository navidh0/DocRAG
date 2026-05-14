"""Tests for the documents domain — upload, list, detail, delete, status, chunks."""
from __future__ import annotations
from django.utils.timezone import now
from datetime import timedelta

import pytest
from unittest.mock import patch, MagicMock

from django.db import ProgrammingError
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from documents.models import Document

pytestmark = pytest.mark.django_db


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _txt_file(name: str = "test.txt", content: bytes = b"hello") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="text/plain")


def _client_for(user) -> APIClient:
    client = APIClient()
    token = str(RefreshToken.for_user(user).access_token)
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


# ─────────────────────────────────────────────
# Upload
# ─────────────────────────────────────────────

@pytest.mark.documents
class TestDocumentUpload:

    def test_upload_txt_succeeds(self, authenticated_client, test_user, mock_embedding_task):
        file = _txt_file("doc.txt", b"some content")
        response = authenticated_client.post("/api/documents/", {"file": file}, format="multipart")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["file_name"] == "doc.txt"
        assert response.data["file_type"] == "txt"
        assert response.data["status"] == "pending"
        assert Document.objects.filter(file_name="doc.txt", user=test_user).exists()

    def test_upload_pdf_succeeds(self, authenticated_client, test_pdf_bytes, mock_embedding_task):
        file = SimpleUploadedFile("report.pdf", test_pdf_bytes, content_type="application/pdf")
        response = authenticated_client.post("/api/documents/", {"file": file}, format="multipart")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["file_type"] == "pdf"

    def test_upload_xlsx_succeeds(self, authenticated_client, test_excel_bytes, mock_embedding_task):
        file = SimpleUploadedFile(
            "sheet.xlsx",
            test_excel_bytes,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response = authenticated_client.post("/api/documents/", {"file": file}, format="multipart")

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["file_type"] == "xlsx"

    def test_upload_schedules_embedding_task(
        self, authenticated_client, mock_embedding_task, django_capture_on_commit_callbacks
    ):
        file = _txt_file(content=b"content")

        with django_capture_on_commit_callbacks(execute=True):
            response = authenticated_client.post("/api/documents/", {"file": file}, format="multipart")

        assert response.status_code == status.HTTP_201_CREATED
        mock_embedding_task.assert_called_once_with(response.data["id"])

    def test_upload_requires_authentication(self, api_client):
        file = _txt_file(content=b"content")
        response = api_client.post("/api/documents/", {"file": file}, format="multipart")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert not Document.objects.exists()

    def test_upload_unsupported_extension_rejected(self, authenticated_client):
        file = SimpleUploadedFile("malware.exe", b"MZ\x90\x00", content_type="application/octet-stream")
        response = authenticated_client.post("/api/documents/", {"file": file}, format="multipart")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Document.objects.exists()

    def test_upload_empty_file_rejected(self, authenticated_client):
        file = _txt_file(content=b"")
        response = authenticated_client.post("/api/documents/", {"file": file}, format="multipart")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Document.objects.exists()

    def test_upload_document_belongs_to_requesting_user(self, authenticated_client, test_user, mock_embedding_task):
        file = _txt_file(content=b"content")
        response = authenticated_client.post("/api/documents/", {"file": file}, format="multipart")

        doc = Document.objects.get(id=response.data["id"])
        assert doc.user_id == test_user.id


# ─────────────────────────────────────────────
# List + Filtering
# ─────────────────────────────────────────────

@pytest.mark.documents
class TestDocumentList:

    def test_list_returns_only_own_documents(self, authenticated_client, test_user, second_user, make_document):
        make_document(file_name="mine.pdf", user=test_user)
        make_document(file_name="theirs.pdf", user=second_user)

        response = authenticated_client.get("/api/documents/")

        assert response.status_code == status.HTTP_200_OK
        names = [d["file_name"] for d in response.data["results"]]
        assert "mine.pdf" in names
        assert "theirs.pdf" not in names

    def test_list_requires_authentication(self, api_client):
        response = api_client.get("/api/documents/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_list_ordered_by_upload_date_descending(self, authenticated_client, test_user, make_document):
       
        make_document(file_name="old.pdf", user=test_user, created_at=now() - timedelta(seconds=10))
        make_document(file_name="new.pdf", user=test_user, created_at=now())

        response = authenticated_client.get("/api/documents/")

        names = [d["file_name"] for d in response.data["results"]]
        assert names.index("new.pdf") < names.index("old.pdf")

    def test_filter_by_status(self, authenticated_client, test_user, make_document):
        make_document(file_name="done.pdf", status="completed", user=test_user)
        make_document(file_name="waiting.pdf", status="pending", user=test_user)

        response = authenticated_client.get("/api/documents/?status=completed")

        assert response.status_code == status.HTTP_200_OK
        names = [d["file_name"] for d in response.data["results"]]
        assert names == ["done.pdf"]

    def test_filter_by_file_type(self, authenticated_client, test_user, make_document):
        make_document(file_name="a.pdf", file_type="pdf", user=test_user)
        make_document(file_name="b.txt", file_type="txt", user=test_user)

        response = authenticated_client.get("/api/documents/?file_type=pdf")

        assert response.status_code == status.HTTP_200_OK
        names = [d["file_name"] for d in response.data["results"]]
        assert names == ["a.pdf"]

    def test_search_by_file_name(self, authenticated_client, test_user, make_document):
        make_document(file_name="annual_report.pdf", user=test_user)
        make_document(file_name="budget.xlsx", user=test_user)

        response = authenticated_client.get("/api/documents/?search=annual")

        assert response.status_code == status.HTTP_200_OK
        names = [d["file_name"] for d in response.data["results"]]
        assert names == ["annual_report.pdf"]

    def test_invalid_status_filter_returns_400(self, authenticated_client):
        response = authenticated_client.get("/api/documents/?status=nonexistent")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_invalid_file_type_filter_returns_400(self, authenticated_client):
        response = authenticated_client.get("/api/documents/?file_type=exe")
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_list_is_paginated(self, authenticated_client, test_user, make_document):
        for i in range(25):
            make_document(file_name=f"doc_{i}.pdf", user=test_user)

        response = authenticated_client.get("/api/documents/")

        assert "results" in response.data
        assert "count" in response.data
        assert len(response.data["results"]) <= 20


# ─────────────────────────────────────────────
# Retrieve + Delete
# ─────────────────────────────────────────────

@pytest.mark.documents
class TestDocumentRetrieveDestroy:

    def test_retrieve_own_document(self, authenticated_client, test_user, make_document):
        doc = make_document(user=test_user)
        response = authenticated_client.get(f"/api/documents/{doc.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(doc.id)
        assert response.data["file_name"] == doc.file_name

    def test_retrieve_returns_core_fields_only(self, authenticated_client, test_user, make_document):
        doc = make_document(user=test_user)
        response = authenticated_client.get(f"/api/documents/{doc.id}/")

        assert set(response.data.keys()) == {"id", "file_name", "file_type", 'status'}

    def test_retrieve_other_users_document_returns_404(self, authenticated_client, second_user, make_document):
        doc = make_document(user=second_user)
        response = authenticated_client.get(f"/api/documents/{doc.id}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_delete_own_document(self, authenticated_client, test_user, make_document):
        doc = make_document(user=test_user)
        response = authenticated_client.delete(f"/api/documents/{doc.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["details"]["id"] == str(doc.id)
        assert response.data["details"]["file_name"] == doc.file_name
        assert not Document.objects.filter(id=doc.id).exists()

    def test_delete_other_users_document_returns_404(self, authenticated_client, second_user, make_document):
        doc = make_document(user=second_user)
        response = authenticated_client.delete(f"/api/documents/{doc.id}/")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert Document.objects.filter(id=doc.id).exists()

    def test_retrieve_nonexistent_document_returns_404(self, authenticated_client):
        import uuid
        response = authenticated_client.get(f"/api/documents/{uuid.uuid4()}/")
        assert response.status_code == status.HTTP_404_NOT_FOUND


# ─────────────────────────────────────────────
# Status
# ─────────────────────────────────────────────

@pytest.mark.documents
class TestDocumentStatus:

    def test_status_returns_all_fields(self, authenticated_client, test_user, make_document):
        doc = make_document(user=test_user, status="pending")
        response = authenticated_client.get(f"/api/documents/{doc.id}/status/")

        assert response.status_code == status.HTTP_200_OK
        assert set(response.data.keys()) >= {"id", "file_name", "status", "created_at", "status_description"}

    @pytest.mark.parametrize("doc_status,expected_description", [
        ("pending", "Waiting to be processed"),
        ("processing", "Extracting text and generating embeddings..."),
        ("completed", "Ready for Q&A"),
        ("failed", "Processing failed. Check file format or logs."),
    ])
    def test_status_description_matches_state(
        self, authenticated_client, test_user, make_document, doc_status, expected_description
    ):
        doc = make_document(user=test_user, status=doc_status)
        response = authenticated_client.get(f"/api/documents/{doc.id}/status/")

        assert response.data["status"] == doc_status
        assert response.data["status_description"] == expected_description

    def test_status_other_users_document_returns_404(self, authenticated_client, second_user, make_document):
        doc = make_document(user=second_user)
        response = authenticated_client.get(f"/api/documents/{doc.id}/status/")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_include_chunks_false_omits_chunk_fields(self, authenticated_client, test_user, make_document):
        doc = make_document(user=test_user, status="completed")
        response = authenticated_client.get(f"/api/documents/{doc.id}/status/")

        assert "total_chunks" not in response.data
        assert "chunks" not in response.data

    def test_include_chunks_true_adds_chunk_fields(self, authenticated_client, test_user, make_document):
        doc = make_document(user=test_user, status="completed")

        mock_cursor = MagicMock()
        mock_cursor.__enter__ = MagicMock(side_effect=ProgrammingError("langchain_pg_embedding"))
        mock_cursor.__exit__ = MagicMock(return_value=False)

        with patch("documents.services.document.connection") as mock_connection:
            mock_connection.cursor.return_value = mock_cursor

            response = authenticated_client.get(f"/api/documents/{doc.id}/status/?include_chunks=true")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["total_chunks"] == 0
        assert response.data["chunks"] == []

    def test_include_chunks_invalid_value_treated_as_false(self, authenticated_client, test_user, make_document):
        doc = make_document(user=test_user, status="completed")
        response = authenticated_client.get(f"/api/documents/{doc.id}/status/?include_chunks=yes")

        assert response.status_code == status.HTTP_200_OK
        assert "total_chunks" not in response.data
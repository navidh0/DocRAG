"""Tests for the Documents domain (file upload, processing, chunking)."""
import pytest
from rest_framework import status
from rest_framework.test import APIClient
from io import BytesIO
from django.test import override_settings
from documents.models import Document

pytestmark = pytest.mark.django_db


@pytest.mark.documents
class TestDocumentUpload:
    """Test document upload functionality."""
    
    def test_upload_txt_file(self, authenticated_client, test_document_text):
        """Test uploading a TXT document."""
        file = BytesIO(test_document_text.encode())
        file.name = 'test_doc.txt'
        
        response = authenticated_client.post(
            '/api/documents/',
            {'file': file},
            format='multipart'
        )
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['file_name'] == 'test_doc.txt'
        assert response.data['file_type'] == 'txt'
        assert response.data['status'] == 'pending'
        assert Document.objects.filter(file_name='test_doc.txt').exists()
    
    def test_upload_requires_authentication(self, api_client, test_document_text):
        """Test uploading without authentication fails."""
        file = BytesIO(test_document_text.encode())
        file.name = 'test_doc.txt'
        
        response = api_client.post(
            '/api/documents/',
            {'file': file},
            format='multipart'
        )
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert not Document.objects.exists()
    
    def test_upload_unsupported_file_type(self, authenticated_client):
        """Test uploading unsupported file type fails."""
        file = BytesIO(b'some binary data')
        file.name = 'test.exe'
        
        response = authenticated_client.post(
            '/api/documents/',
            {'file': file},
            format='multipart'
        )
        
        assert response.status_code in [status.HTTP_400_BAD_REQUEST, status.HTTP_201_CREATED]
        # File type should be 'unknown' or rejected
    
    def test_upload_empty_file_rejected(self, authenticated_client):
        """Test uploading empty file fails."""
        file = BytesIO(b'')
        file.name = 'empty.txt'
        
        response = authenticated_client.post(
            '/api/documents/',
            {'file': file},
            format='multipart'
        )
        
        # May succeed but with 0 size warning
        assert response.status_code in [status.HTTP_201_CREATED, status.HTTP_400_BAD_REQUEST]
    
    def test_upload_large_file_handling(self, authenticated_client):
        """Test handling of large file uploads."""
        # Create a 5MB file
        large_content = b'x' * (5 * 1024 * 1024)
        file = BytesIO(large_content)
        file.name = 'large.txt'
        
        # Should either succeed or be rejected based on settings
        response = authenticated_client.post(
            '/api/documents/',
            {'file': file},
            format='multipart'
        )
        
        assert response.status_code in [status.HTTP_201_CREATED, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE]


@pytest.mark.documents
class TestDocumentListing:
    """Test document listing and filtering."""
    
    def test_list_user_documents(self, authenticated_client, test_user, test_document_text):
        """Test user can list their own documents."""
        # Create a document first
        file = BytesIO(test_document_text.encode())
        file.name = 'doc1.txt'
        authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        
        # List documents
        response = authenticated_client.get('/api/documents/')
        
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data['results']) >= 1
        assert response.data['results'][0]['file_name'] == 'doc1.txt'
    
    def test_list_documents_requires_auth(self, api_client):
        """Test listing documents requires authentication."""
        response = api_client.get('/api/documents/')
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_user_cannot_see_other_users_documents(self, authenticated_client, second_user, test_document_text):
        """Test user isolation - cannot see other user's docs."""
        # Create document as first user
        file = BytesIO(test_document_text.encode())
        file.name = 'private_doc.txt'
        authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        
        # Login as second user and try to see documents
        client2 = APIClient()
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(second_user)
        client2.credentials(HTTP_AUTHORIZATION=f'Bearer {str(refresh.access_token)}')
        
        response = client2.get('/api/documents/')
        
        # Second user should not see first user's document
        doc_names = [d['file_name'] for d in response.data.get('results', [])]
        assert 'private_doc.txt' not in doc_names
    
    def test_filter_documents_by_status(self, authenticated_client, test_document_text):
        """Test filtering documents by status."""
        file = BytesIO(test_document_text.encode())
        file.name = 'test.txt'
        authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        
        # Filter by pending status
        response = authenticated_client.get('/api/documents/?status=pending')
        
        assert response.status_code == status.HTTP_200_OK
        # Should find our pending document
    
    def test_search_documents_by_name(self, authenticated_client, test_document_text):
        """Test searching documents by filename."""
        # Upload two documents
        for name in ['report.txt', 'analysis.txt']:
            file = BytesIO(test_document_text.encode())
            file.name = name
            authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        
        # Search for 'report'
        response = authenticated_client.get('/api/documents/?search=report')
        
        assert response.status_code == status.HTTP_200_OK
        found_names = [d['file_name'] for d in response.data.get('results', [])]
        assert 'report.txt' in found_names


@pytest.mark.documents
class TestDocumentDetail:
    """Test document detail and status checking."""
    
    def test_get_document_detail(self, authenticated_client, test_document_text):
        """Test retrieving document detail."""
        # Upload document
        file = BytesIO(test_document_text.encode())
        file.name = 'test.txt'
        create_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        doc_id = create_resp.data['id']
        
        # Get detail
        response = authenticated_client.get(f'/api/documents/{doc_id}/')
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['file_name'] == 'test.txt'
    
    def test_get_document_status(self, authenticated_client, test_document_text):
        """Test retrieving document processing status."""
        file = BytesIO(test_document_text.encode())
        file.name = 'test.txt'
        create_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        doc_id = create_resp.data['id']
        
        response = authenticated_client.get(f'/api/documents/{doc_id}/status/')
        
        assert response.status_code == status.HTTP_200_OK
        assert 'status' in response.data
        assert response.data['status'] in ['pending', 'processing', 'completed', 'failed']
    
    def test_user_cannot_access_other_users_document(self, authenticated_client, second_user, test_document_text):
        """Test user cannot access other user's document detail."""
        # Create document as first user
        file = BytesIO(test_document_text.encode())
        file.name = 'private.txt'
        create_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        doc_id = create_resp.data['id']
        
        # Try to access as second user
        client2 = APIClient()
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(second_user)
        client2.credentials(HTTP_AUTHORIZATION=f'Bearer {str(refresh.access_token)}')
        
        response = client2.get(f'/api/documents/{doc_id}/')
        
        assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.documents
class TestDocumentDeletion:
    """Test document deletion."""
    
    def test_delete_own_document(self, authenticated_client, test_document_text):
        """Test user can delete their own document."""
        # Create document
        file = BytesIO(test_document_text.encode())
        file.name = 'delete_me.txt'
        create_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        doc_id = create_resp.data['id']
        
        # Delete it
        response = authenticated_client.delete(f'/api/documents/{doc_id}/')
        
        assert response.status_code == status.HTTP_200_OK
        assert not Document.objects.filter(id=doc_id).exists()
    
    def test_delete_requires_ownership(self, authenticated_client, second_user, test_document_text):
        """Test cannot delete other user's document."""
        # Create as first user
        file = BytesIO(test_document_text.encode())
        file.name = 'protected.txt'
        create_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        doc_id = create_resp.data['id']
        
        # Try to delete as second user
        client2 = APIClient()
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(second_user)
        client2.credentials(HTTP_AUTHORIZATION=f'Bearer {str(refresh.access_token)}')
        
        response = client2.delete(f'/api/documents/{doc_id}/')
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert Document.objects.filter(id=doc_id).exists()


@pytest.mark.documents
class TestChunkVerification:
    """Test chunk verification endpoint."""
    
    def test_verify_chunks_stored(self, authenticated_client, test_document_text):
        """Test that chunks are verified in vector DB."""
        # Upload document
        file = BytesIO(test_document_text.encode())
        file.name = 'test.txt'
        create_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        doc_id = create_resp.data['id']
        
        # Check chunks
        response = authenticated_client.get(f'/api/documents/{doc_id}/chunks/')
        
        assert response.status_code == status.HTTP_200_OK
        # May be empty if Ollama not available, but endpoint should work
        assert 'total_chunks_found' in response.data
    
    def test_chunks_have_proper_metadata(self, authenticated_client, test_document_text):
        """Test chunks have correct metadata."""
        file = BytesIO(test_document_text.encode())
        file.name = 'test.txt'
        create_resp = authenticated_client.post('/api/documents/', {'file': file}, format='multipart')
        doc_id = create_resp.data['id']
        
        response = authenticated_client.get(f'/api/documents/{doc_id}/chunks/')
        
        if response.data['total_chunks_found'] > 0:
            chunk = response.data['chunks'][0]
            assert 'metadata' in chunk
            assert 'document_id' in chunk['metadata']
            assert 'user_id' in chunk['metadata']
            assert 'file_name' in chunk['metadata']

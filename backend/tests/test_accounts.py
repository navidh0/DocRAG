"""Tests for the Accounts domain (authentication and user management)."""
import pytest
from django.contrib.auth import get_user_model
from rest_framework import status
from accounts.views import REFRESH_COOKIE_NAME

User = get_user_model()


@pytest.mark.auth
@pytest.mark.django_db
class TestUserRegistration:
    """Test user registration endpoint."""
    
    def test_register_with_valid_data(self, api_client):
        """Test successful user registration."""
        data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!'
        }
        response = api_client.post('/api/auth/register/', data)
        
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['message'] == 'Account created successfully.'
        assert response.data['user']['username'] == 'newuser'
        assert response.data['user']['email'] == 'newuser@example.com'
        assert User.objects.filter(username='newuser').exists()
    
    def test_register_with_mismatched_passwords(self, api_client):
        """Test registration fails with mismatched passwords."""
        data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': 'SecurePass123!',
            'password_confirm': 'DifferentPass123!'
        }
        response = api_client.post('/api/auth/register/', data)
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not User.objects.filter(username='newuser').exists()
    
    def test_register_with_weak_password(self, api_client):
        """Test registration fails with weak password."""
        data = {
            'username': 'newuser',
            'email': 'newuser@example.com',
            'password': '123',
            'password_confirm': '123'
        }
        response = api_client.post('/api/auth/register/', data)
        
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not User.objects.filter(username='newuser').exists()
    
    def test_register_with_duplicate_username(self, test_user, api_client):
        """Test registration fails with duplicate username."""
        data = {
            'username': 'testuser',  # Already exists
            'email': 'different@example.com',
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!'
        }
        response = api_client.post('/api/auth/register/', data)
        
        assert response.status_code == status.HTTP_409_CONFLICT
        assert User.objects.filter(username='testuser').count() == 1
    
    def test_register_with_duplicate_email(self, test_user, api_client):
        """Test registration fails with duplicate email."""
        data = {
            'username': 'newuser',
            'email': 'test@example.com',  # Already exists
            'password': 'SecurePass123!',
            'password_confirm': 'SecurePass123!'
        }
        response = api_client.post('/api/auth/register/', data)
        
        assert response.status_code == status.HTTP_409_CONFLICT


@pytest.mark.auth
@pytest.mark.django_db
class TestUserLogin:
    """Test user login endpoint."""
    
    def test_login_with_correct_credentials(self, test_user, api_client):
        data = {'username': 'testuser', 'password': 'TestPass123!'}
        response = api_client.post('/api/auth/login/', data)

        assert response.status_code == status.HTTP_200_OK
        assert 'access' in response.data
        assert 'refresh' not in response.data                        # refresh is in cookie now
        assert REFRESH_COOKIE_NAME in response.cookies               # verify cookie was set
        assert response.data['user']['username'] == 'testuser'
    
    def test_login_with_incorrect_password(self, test_user, api_client):
        """Test login fails with incorrect password."""
        data = {
            'username': 'testuser',
            'password': 'WrongPassword123!'
        }
        response = api_client.post('/api/auth/login/', data)
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert 'access' not in response.data
    
    def test_login_with_nonexistent_user(self, api_client):
        """Test login fails with non-existent user."""
        data = {
            'username': 'nonexistent',
            'password': 'SomePassword123!'
        }
        response = api_client.post('/api/auth/login/', data)
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_login_returns_user_info(self, test_user, api_client):
        """Test that login returns user information."""
        data = {
            'username': 'testuser',
            'password': 'TestPass123!'
        }
        response = api_client.post('/api/auth/login/', data)
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['user']['email'] == 'test@example.com'
        assert response.data['user']['question_count'] == 0


@pytest.mark.auth
@pytest.mark.django_db
class TestUserProfile:
    """Test user profile endpoints."""
    
    def test_get_current_user_profile(self, authenticated_client):
        """Test retrieving current user profile."""
        response = authenticated_client.get('/api/auth/me/')
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['username'] == 'testuser'
        assert response.data['email'] == 'test@example.com'
    
    def test_get_profile_without_auth(self, api_client):
        """Test profile endpoint requires authentication."""
        response = api_client.get('/api/auth/me/')
        
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_update_user_profile(self, authenticated_client):
        """Test updating user profile."""
        data = {
            'email': 'newemail@example.com'
        }
        response = authenticated_client.patch('/api/auth/me/', data)
        
        assert response.status_code == status.HTTP_200_OK
        assert response.data['email'] == 'newemail@example.com'


@pytest.mark.auth
@pytest.mark.django_db
class TestUserIsolation:
    """Test user data isolation."""
    
    def test_user_cannot_view_other_user_profile(self, authenticated_client, second_user):
        """Test that users cannot access other users' profiles."""
        # This would depend on your implementation
        # If there's an endpoint to get user by ID, test it doesn't leak data
        response = authenticated_client.get(f'/api/users/{second_user.id}/')
        
        # Should either be 404 or 403 depending on implementation
        assert response.status_code in [status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN]


@pytest.mark.auth
@pytest.mark.django_db
class TestTokenRefresh:
    """Test JWT token refresh functionality."""
    
    def test_refresh_access_token(self, test_user, api_client):
        login_data = {'username': 'testuser', 'password': 'TestPass123!'}
        api_client.post('/api/auth/login/', login_data)              # cookie stored on client automatically

        response = api_client.post('/api/auth/refresh/')             # cookie sent automatically

        assert response.status_code == status.HTTP_200_OK
        assert 'access' in response.data
        assert 'refresh' not in response.data    
    
    def test_refresh_with_invalid_token(self, api_client):
        api_client.cookies['refresh_token'] = 'invalid.token.here'  # set bad token in cookie
        response = api_client.post('/api/auth/refresh/')

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

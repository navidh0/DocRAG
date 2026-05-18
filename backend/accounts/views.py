from __future__ import annotations
from typing import Any, cast

from django.conf import settings
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken

from .exceptions import MissingRefreshTokenError
from .serializers import (
    CustomTokenObtainPairSerializer,
    RegisterInputSerializer,
    UserOutputSerializer,
    UserUpdateInputSerializer,
)
from .services import logout_user, register_user, update_user_profile

REFRESH_COOKIE_NAME = settings.REFRESH_COOKIE_NAME
REFRESH_COOKIE_PATH = settings.REFRESH_COOKIE_PATH

# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=refresh_token,
        httponly=True,
        secure=settings.REFRESH_COOKIE_SECURE,
        samesite=settings.REFRESH_COOKIE_SAMESITE,
        path=REFRESH_COOKIE_PATH,
        max_age=settings.REFRESH_COOKIE_MAX_AGE,
    )


def _delete_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH)

# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

@extend_schema(tags=["Auth"])
class RegisterView(APIView):
    """
    POST /api/auth/register/
    Public — creates a new user account.
    """

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Register a new user",
        request=RegisterInputSerializer,
        responses={
            201: OpenApiResponse(
                response=UserOutputSerializer,
                description="Account created successfully.",
                examples=[
                    OpenApiExample(
                        "Success",
                        value={
                            "message": "Account created successfully.",
                            "user": {
                                "id": "550e8400-e29b-41d4-a716-446655440000",
                                "username": "navid",
                                "email": "navid@example.com",
                                "question_count": 0,
                                "created_at": "2026-01-01T00:00:00Z",
                            },
                        },
                        response_only=True,
                        status_codes=["201"],
                    )
                ],
            ),
            400: OpenApiResponse(description="Validation error — passwords mismatch etc."),
            409: OpenApiResponse(description="Email or username already in use."),
        },
    )
    def post(self, request):
        serializer = RegisterInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = cast(dict[str, Any], serializer.validated_data)

        user = register_user(
            username=data["username"],
            email=data["email"],
            password=data["password"],
        )
        return Response(
            {"message": "Account created successfully.", "user": UserOutputSerializer(user).data},
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@extend_schema(tags=["Auth"])
class LoginView(TokenObtainPairView):
    """
    POST /api/auth/login/
    Returns access token in body + user info.
    Sets refresh token as an HTTP-only cookie.
    """

    serializer_class = CustomTokenObtainPairSerializer
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Login — obtain tokens",
        responses={
            200: OpenApiResponse(
                description="Access token + user info. Refresh token is set as HTTP-only cookie.",
                examples=[
                    OpenApiExample(
                        "Success",
                        value={
                            "access": "<jwt_access_token>",
                            "user": {
                                "id": "550e8400-e29b-41d4-a716-446655440000",
                                "username": "navid",
                                "email": "navid@example.com",
                                "question_count": 0,
                                "created_at": "2026-01-01T00:00:00Z",
                            },
                        },
                        response_only=True,
                        status_codes=["200"],
                    )
                ],
            ),
            401: OpenApiResponse(description="Invalid credentials."),
        },
    )
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            data = cast(dict[str, Any], response.data)
            refresh_token = data.pop("refresh", None)
            if refresh_token:
                _set_refresh_cookie(response, refresh_token)
        return response


# ---------------------------------------------------------------------------
# Refresh  (reads cookie — no body required)
# ---------------------------------------------------------------------------

@extend_schema(tags=["Auth"])
class CookieTokenRefreshView(TokenRefreshView):
    """
    POST /api/auth/refresh/
    Reads the refresh token from the HTTP-only cookie.
    Returns a new access token and rotates the cookie.
    No request body required.
    """

    @extend_schema(
        summary="Refresh access token (cookie-based)",
        request=None,
        responses={
            200: OpenApiResponse(
                description="New access token issued. Refresh cookie is rotated.",
                examples=[
                    OpenApiExample(
                        "Success",
                        value={"access": "<new_jwt_access_token>"},
                        response_only=True,
                        status_codes=["200"],
                    )
                ],
            ),
            400: OpenApiResponse(description="Refresh token cookie missing."),
            401: OpenApiResponse(description="Refresh token invalid or expired."),
        },
    )
    def post(self, request, *args, **kwargs):
        refresh_token = request.COOKIES.get(REFRESH_COOKIE_NAME)
        if not refresh_token:
            raise MissingRefreshTokenError()

        serializer = self.get_serializer(data={"refresh": refresh_token})

        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0]) from e  # InvalidToken is a DRF APIException → 401

        response = Response(serializer.validated_data, status=status.HTTP_200_OK)

        new_refresh = response.data.pop("refresh", None)
        if new_refresh:
            _set_refresh_cookie(response, new_refresh)

        return response


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

@extend_schema(tags=["Auth"])
class LogoutView(APIView):
    """
    POST /api/auth/logout/
    Blacklists the refresh token from the cookie and clears it.
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Logout — blacklist refresh token",
        request=None,
        responses={
            200: OpenApiResponse(
                description="Logged out successfully.",
                examples=[
                    OpenApiExample(
                        "Success",
                        value={"message": "Logout successful."},
                        response_only=True,
                        status_codes=["200"],
                    )
                ],
            ),
            400: OpenApiResponse(description="Refresh token cookie missing or invalid."),
        },
    )
    def post(self, request):
        logout_user(refresh_token=request.COOKIES.get(REFRESH_COOKIE_NAME))
        response = Response({"message": "Logout successful."}, status=status.HTTP_200_OK)
        _delete_refresh_cookie(response)
        return response


# ---------------------------------------------------------------------------
# Me
# ---------------------------------------------------------------------------

@extend_schema(tags=["Auth"])
class MeView(APIView):
    """
    GET  /api/auth/me/  — current user profile
    PATCH /api/auth/me/ — update username / email
    """

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Get current user profile",
        responses={
            200: OpenApiResponse(
                response=UserOutputSerializer,
                description="Current user's profile.",
                examples=[
                    OpenApiExample(
                        "Profile",
                        value={
                            "id": "550e8400-e29b-41d4-a716-446655440000",
                            "username": "navid",
                            "email": "navid@example.com",
                            "question_count": 12,
                            "created_at": "2026-01-01T00:00:00Z",
                        },
                        response_only=True,
                        status_codes=["200"],
                    )
                ],
            ),
        },
    )
    def get(self, request):
        return Response(UserOutputSerializer(request.user).data)

    @extend_schema(
        summary="Update current user profile",
        request=UserUpdateInputSerializer,
        responses={
            200: OpenApiResponse(
                response=UserOutputSerializer,
                description="Updated profile.",
                examples=[
                    OpenApiExample(
                        "Updated",
                        value={
                            "id": "550e8400-e29b-41d4-a716-446655440000",
                            "username": "navid_updated",
                            "email": "new@example.com",
                            "question_count": 12,
                            "created_at": "2026-01-01T00:00:00Z",
                        },
                        response_only=True,
                        status_codes=["200"],
                    )
                ],
            ),
            400: OpenApiResponse(description="Validation error."),
            409: OpenApiResponse(description="Email or username already in use."),
        },
    )
    def patch(self, request):
        serializer = UserUpdateInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = cast(dict[str, Any], serializer.validated_data)

        user = update_user_profile(
            user=request.user,
            username=data.get("username"),
            email=data.get("email"),
        )
        return Response(UserOutputSerializer(user).data)
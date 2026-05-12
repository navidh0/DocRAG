from __future__ import annotations
from typing import Any

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import User


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

class UserOutputSerializer(serializers.ModelSerializer):
    """Read-only representation of a user — used in all responses."""

    class Meta:
        model = User
        fields = ("id", "username", "email", "question_count", "created_at")
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Input — Register
# ---------------------------------------------------------------------------

class RegisterInputSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password": "Passwords do not match."})
        return attrs


# ---------------------------------------------------------------------------
# Input — Profile update (PATCH /me/)
# ---------------------------------------------------------------------------

class UserUpdateInputSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, required=False)
    email = serializers.EmailField(required=False)

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("At least one field must be provided.")
        return attrs


# ---------------------------------------------------------------------------
# Login (extends simplejwt — output only, no write logic)
# ---------------------------------------------------------------------------

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Augments the standard token pair response with basic user data.
    The view is responsible for moving the refresh token into an HTTP-only cookie;
    this serializer simply exposes it so the view can extract and strip it.
    """

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        data: dict[str, Any] = super().validate(attrs)
        data["user"] = UserOutputSerializer(self.user).data
        return data
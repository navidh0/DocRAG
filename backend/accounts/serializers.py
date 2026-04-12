from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import User


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password]
    )
    password_confirm = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password", "password_confirm")

    def validate(self, attrs):
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password": "Passwords do not match."})
        
        # Validate email uniqueness
        if User.objects.filter(email=attrs.get("email")).exists():
            raise serializers.ValidationError({"email": "This email is already in use."})
        
        return attrs

    def create(self, validated_data):
        validated_data.pop("password_confirm")
        user = User.objects.create_user(**validated_data)
        return user


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "username", "email", "question_count", "created_at")
        read_only_fields = ("id", "question_count", "created_at")
    
    def validate_email(self, value):
        """Ensure email uniqueness (excluding current user in updates)."""
        user = self.instance
        if User.objects.filter(email=value).exclude(pk=user.pk if user else None).exists():
            raise serializers.ValidationError("This email is already in use.")
        return value


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Adds basic user info to the login response alongside the tokens."""

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data
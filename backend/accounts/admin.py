from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin configuration for the custom User model."""

    # Columns shown in the changelist
    list_display = (
        "username", "email", "question_count",
        "is_staff", "is_active", "created_at",
    )
    list_filter = ("is_staff", "is_superuser", "is_active", "groups")
    search_fields = ("username", "email", "id")
    ordering = ("-created_at",)
    readonly_fields = ("id", "question_count", "created_at", "updated_at")

    # Detail view fieldsets – extend the default ones with our extra fields
    fieldsets = BaseUserAdmin.fieldsets + (
        (_("RAG metadata"), {
            "fields": ("question_count", "created_at", "updated_at"),
        }),
    )

    # Add-user form fieldsets
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "email", "password1", "password2"),
        }),
    )
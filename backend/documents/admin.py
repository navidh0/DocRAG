from django.contrib import admin
from django.utils.html import format_html

from .models import Document


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    """Admin configuration for the Document model."""

    list_display = (
        "file_name", "file_type", "status_badge",
        "owner_username", "created_at",
    )
    list_filter = ("status", "file_type", "created_at")
    search_fields = ("file_name", "user__username", "user__email", "id")
    ordering = ("-created_at",)
    readonly_fields = ("id", "file_name", "file_type", "created_at", "user")

    fieldsets = (
        ("File info", {
            "fields": ("id", "file", "file_name", "file_type"),
        }),
        ("Processing", {
            "fields": ("status",),
        }),
        ("Ownership", {
            "fields": ("user", "created_at"),
        }),
    )

    # ------------------------------------------------------------------ #
    # Custom list columns
    # ------------------------------------------------------------------ #

    @admin.display(description="Owner")
    def owner_username(self, obj):
        return obj.user.username

    @admin.display(description="Status")
    def status_badge(self, obj):
        colours = {
            "pending":    "#f59e0b",   # amber
            "processing": "#3b82f6",   # blue
            "completed":  "#22c55e",   # green
            "failed":     "#ef4444",   # red
        }
        colour = colours.get(obj.status, "#6b7280")
        return format_html(
            '<span style="color:{};font-weight:600;">{}</span>',
            colour,
            obj.get_status_display(),
        )

    # ------------------------------------------------------------------ #
    # Bulk actions
    # ------------------------------------------------------------------ #

    @admin.action(description="Mark selected documents as failed")
    def mark_failed(self, request, queryset):
        updated = queryset.update(status="failed")
        self.message_user(request, f"{updated} document(s) marked as failed.")

    @admin.action(description="Mark selected documents as pending (re-queue)")
    def mark_pending(self, request, queryset):
        updated = queryset.update(status="pending")
        self.message_user(request, f"{updated} document(s) reset to pending.")

    actions = ["mark_failed", "mark_pending"]
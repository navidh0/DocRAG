from django.contrib import admin
from django.utils.html import format_html

from .models import QuestionActivity


@admin.register(QuestionActivity)
class QuestionActivityAdmin(admin.ModelAdmin):
    """Admin configuration for the QuestionActivity model."""

    list_display = (
        "short_question", "owner_username", "status_badge",
        "response_time_ms", "sources_count", "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = ("question", "answer", "user__username", "user__email")
    ordering = ("-created_at",)
    readonly_fields = (
        "user", "document", "question", "answer",
        "sources", "response_time_ms", "status", "created_at",
    )

    fieldsets = (
        ("Question", {
            "fields": ("user", "document", "question"),
        }),
        ("Answer", {
            "fields": ("answer", "sources"),
        }),
        ("Performance", {
            "fields": ("status", "response_time_ms", "created_at"),
        }),
    )

    # ------------------------------------------------------------------ #
    # Custom list columns
    # ------------------------------------------------------------------ #

    @admin.display(description="Question")
    def short_question(self, obj):
        return obj.question[:80] + "…" if len(obj.question) > 80 else obj.question

    @admin.display(description="User")
    def owner_username(self, obj):
        return obj.user.username

    @admin.display(description="Status")
    def status_badge(self, obj):
        colours = {
            "success":   "#22c55e",  # green
            "no_answer": "#f59e0b",  # amber
            "error":     "#ef4444",  # red
        }
        colour = colours.get(obj.status, "#6b7280")
        return format_html(
            '<span style="color:{};font-weight:600;">{}</span>',
            colour,
            obj.get_status_display(),
        )

    @admin.display(description="Sources")
    def sources_count(self, obj):
        return len(obj.sources) if obj.sources else 0

    # ------------------------------------------------------------------ #
    # Bulk actions
    # ------------------------------------------------------------------ #

    @admin.action(description="Delete selected activity records")
    def delete_selected_activity(self, request, queryset):
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"{count} activity record(s) deleted.")

    actions = ["delete_selected_activity"]

    # Disable add permission — activities are system-generated only
    def has_add_permission(self, request):
        return False
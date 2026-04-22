from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.html import format_html

from pxtx.core.models import (
    ActivityLog,
    ApiToken,
    Comment,
    GithubRef,
    Issue,
    IssueReference,
    Milestone,
    User,
)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ["username", "is_active", "is_staff", "is_superuser"]
    list_filter = ["is_active", "is_staff", "is_superuser"]
    search_fields = ["username"]
    ordering = ["username"]
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Dates", {"fields": ("last_login",)}),
    )
    add_fieldsets = (
        (
            None,
            {"classes": ("wide",), "fields": ("username", "password1", "password2")},
        ),
    )


@admin.register(Milestone)
class MilestoneAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "target_date", "released_at"]
    list_filter = ["released_at"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ["name"]}
    ordering = ["-target_date"]


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    list_display = [
        "number",
        "title",
        "status",
        "priority",
        "is_highlighted",
        "milestone",
        "assignee",
        "updated_at",
    ]
    list_filter = ["status", "priority", "source", "is_highlighted", "milestone"]
    search_fields = ["title", "description", "assignee"]
    raw_id_fields = ["milestone"]
    readonly_fields = ["number", "created_at", "updated_at", "closed_at"]
    ordering = ["-updated_at"]


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ["issue", "author", "created_at", "edited_at"]
    search_fields = ["body", "author"]
    raw_id_fields = ["issue"]
    readonly_fields = ["created_at", "edited_at"]


@admin.register(GithubRef)
class GithubRefAdmin(admin.ModelAdmin):
    list_display = ["issue", "kind", "repo", "number", "sha", "state"]
    list_filter = ["kind", "state"]
    search_fields = ["repo", "title"]
    raw_id_fields = ["issue"]


@admin.register(IssueReference)
class IssueReferenceAdmin(admin.ModelAdmin):
    list_display = ["from_issue", "to_issue", "created_at"]
    raw_id_fields = ["from_issue", "to_issue"]


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    """Admin is the only place to mint tokens. The generated plaintext is
    flashed to the admin user exactly once — this is the only copy, the DB
    only sees the hash.
    """

    list_display = ["name", "user", "created_at", "last_used_at"]
    search_fields = ["name", "user__username"]
    readonly_fields = ["token_hash", "created_at", "last_used_at"]

    def get_fields(self, request, obj=None):
        if obj is None:
            return ["name", "user"]
        return ["name", "user", "token_hash", "created_at", "last_used_at"]

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
            return
        token, plaintext = ApiToken.create(user=obj.user, name=obj.name)
        # The admin uses ``obj.pk`` for its post-save redirect, so point it
        # at the newly created row.
        obj.pk = token.pk
        obj.token_hash = token.token_hash
        messages.warning(
            request,
            format_html(
                "API token for {} minted. Copy it now — it will not be shown "
                "again:<br><code>{}</code>",
                obj.name,
                plaintext,
            ),
        )


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ["timestamp", "action_type", "actor", "content_type", "object_id"]
    list_filter = ["action_type", "content_type"]
    search_fields = ["actor", "action_type"]
    readonly_fields = [
        "content_type",
        "object_id",
        "action_type",
        "actor",
        "timestamp",
        "data",
    ]
    ordering = ["-timestamp"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

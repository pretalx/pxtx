from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from rest_framework import serializers

from pxtx.core.models import (
    ActivityLog,
    Comment,
    GithubRef,
    GithubRefKind,
    Issue,
    Milestone,
)


class MilestoneNestedSerializer(serializers.ModelSerializer):
    class Meta:
        model = Milestone
        fields = ["slug", "name"]


class MilestoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = Milestone
        fields = [
            "slug",
            "name",
            "description",
            "target_date",
            "released_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]


class GithubRefSerializer(serializers.ModelSerializer):
    url = serializers.ReadOnlyField()
    display = serializers.ReadOnlyField()

    class Meta:
        model = GithubRef
        fields = [
            "id",
            "kind",
            "repo",
            "number",
            "sha",
            "title",
            "state",
            "url",
            "display",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate(self, attrs):
        kind = attrs.get("kind")
        number = attrs.get("number")
        sha = attrs.get("sha", "")
        if kind in (GithubRefKind.ISSUE, GithubRefKind.PR) and number is None:
            raise serializers.ValidationError({"number": "required for issue/pr refs"})
        if kind == GithubRefKind.COMMIT and not sha:
            raise serializers.ValidationError({"sha": "required for commit refs"})
        return attrs


class IssueRefSummarySerializer(serializers.ModelSerializer):
    slug = serializers.ReadOnlyField()

    class Meta:
        model = Issue
        fields = ["number", "slug", "title", "status"]


class CommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Comment
        fields = ["id", "issue", "author", "body", "created_at", "edited_at"]
        read_only_fields = ["id", "issue", "author", "created_at", "edited_at"]

    def create(self, validated_data):
        comment = Comment(**validated_data)
        comment.save(actor=self.context.get("actor", ""))
        return comment

    def update(self, instance, validated_data):
        instance.body = validated_data.get("body", instance.body)
        instance.edited_at = timezone.now()
        instance.save(actor=self.context.get("actor", ""))
        return instance


class IssueSerializer(serializers.ModelSerializer):
    slug = serializers.ReadOnlyField()
    milestone = serializers.SlugRelatedField(
        slug_field="slug",
        queryset=Milestone.objects.all(),
        allow_null=True,
        required=False,
    )
    github_refs = GithubRefSerializer(many=True, read_only=True)
    comment_count = serializers.SerializerMethodField()
    references_out = serializers.SerializerMethodField()
    references_in = serializers.SerializerMethodField()

    class Meta:
        model = Issue
        fields = [
            "number",
            "slug",
            "title",
            "description",
            "effort_minutes",
            "priority",
            "is_highlighted",
            "status",
            "blocked_reason",
            "source",
            "milestone",
            "order_in_milestone",
            "order_in_priority",
            "assignee",
            "interested_parties",
            "links",
            "github_refs",
            "comment_count",
            "references_out",
            "references_in",
            "created_at",
            "updated_at",
            "closed_at",
        ]
        read_only_fields = [
            "number",
            "github_refs",
            "comment_count",
            "references_out",
            "references_in",
            "created_at",
            "updated_at",
            "closed_at",
        ]

    def get_comment_count(self, obj):
        # IssueViewSet annotates ``comment_count`` on the list queryset to
        # avoid N+1 COUNT queries. Fall back to a live count for instances
        # served outside that queryset (e.g. after a create or transition).
        cached = getattr(obj, "comment_count", None)
        if cached is not None:
            return cached
        return obj.comments.count()

    def get_references_out(self, obj):
        # IssueViewSet prefetches ``references_from`` with the ``to_issue``
        # side select_related, so iterating the prefetched manager is O(1)
        # queries. The direct-query fallback below is only hit for single
        # instances served outside the list queryset.
        refs = obj.references_from.all()
        return IssueRefSummarySerializer([r.to_issue for r in refs], many=True).data

    def get_references_in(self, obj):
        refs = obj.references_to.all()
        return IssueRefSummarySerializer([r.from_issue for r in refs], many=True).data

    def validate(self, attrs):
        status = attrs.get("status", getattr(self.instance, "status", None))
        if status == "blocked":
            reason = attrs.get(
                "blocked_reason", getattr(self.instance, "blocked_reason", "")
            )
            if not reason:
                raise serializers.ValidationError(
                    {"blocked_reason": "required when status is blocked"}
                )
        return attrs

    def create(self, validated_data):
        issue = Issue(**validated_data)
        issue.save(actor=self.context.get("actor", ""))
        return issue

    def update(self, instance, validated_data):
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save(actor=self.context.get("actor", ""))
        return instance


class IssueReferenceCreateSerializer(serializers.Serializer):
    to_issue = serializers.IntegerField()

    def validate_to_issue(self, value):
        try:
            return Issue.objects.get(number=value)
        except Issue.DoesNotExist as exc:
            raise serializers.ValidationError("no such issue") from exc


class StatusActionSerializer(serializers.Serializer):
    blocked_reason = serializers.CharField(required=False, allow_blank=True)


class ActivityLogSerializer(serializers.ModelSerializer):
    content_type = serializers.CharField(source="content_type.model", read_only=True)
    changes = serializers.ReadOnlyField()

    class Meta:
        model = ActivityLog
        fields = [
            "id",
            "content_type",
            "object_id",
            "action_type",
            "actor",
            "timestamp",
            "data",
            "changes",
        ]
        read_only_fields = fields


class ActivityLogCreateSerializer(serializers.Serializer):
    """Custom log entry: claude-code narrates something about an issue."""

    action_type = serializers.CharField(max_length=200)
    issue = serializers.IntegerField()
    data = serializers.JSONField(required=False)

    def validate_issue(self, value):
        try:
            return Issue.objects.get(number=value)
        except Issue.DoesNotExist as exc:
            raise serializers.ValidationError("no such issue") from exc

    def create(self, validated_data):
        issue = validated_data["issue"]
        return ActivityLog.objects.create(
            content_type=ContentType.objects.get_for_model(Issue),
            object_id=issue.pk,
            action_type=validated_data["action_type"],
            actor=self.context.get("actor", ""),
            data=validated_data.get("data") or {},
        )


class RenderSerializer(serializers.Serializer):
    text = serializers.CharField(allow_blank=True)

from django.db.models import Count, Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.mixins import CreateModelMixin, DestroyModelMixin, ListModelMixin
from rest_framework.response import Response
from rest_framework.views import APIView

from pxtx.core.api.filters import ActivityLogFilter, IssueFilter
from pxtx.core.api.pagination import (
    ChronologicalCursorPagination,
    TimestampCursorPagination,
)
from pxtx.core.api.serializers import (
    ActivityLogCreateSerializer,
    ActivityLogSerializer,
    CommentSerializer,
    GithubRefSerializer,
    IssueReferenceCreateSerializer,
    IssueSerializer,
    MilestoneSerializer,
    RenderSerializer,
    StatusActionSerializer,
)
from pxtx.core.models import (
    ActivityLog,
    Comment,
    GithubRef,
    Issue,
    IssueReference,
    Milestone,
    Status,
)
from pxtx.core.text import render_markdown


def _actor(request):
    """Label for ActivityLog entries and comment authorship.

    Prefers the ``X-Pxtx-Actor`` header (set automatically by the CLI as
    ``claude-<branch>``) so one shared token can still attribute work to a
    specific caller. Falls back to ``ApiToken.name`` when the header is
    missing — e.g. ad-hoc ``curl`` calls or older CLI versions.
    TokenAuthentication is the only authenticator wired in, so
    ``request.auth`` is always an ``ApiToken`` here.
    """
    header = request.META.get("HTTP_X_PXTX_ACTOR", "").strip()
    if header:
        return header
    return request.auth.name


class IssueViewSet(viewsets.ModelViewSet):
    """Full CRUD for issues, keyed by ``number`` rather than pk.

    ``PATCH`` intentionally rejects ``status`` — the status machine is only
    driven through the explicit action endpoints (``/issues/<n>/<action>/``)
    so the ActivityLog can record the transition with its own event type.
    """

    serializer_class = IssueSerializer
    filterset_class = IssueFilter
    lookup_field = "number"
    lookup_url_kwarg = "number"
    http_method_names = ["get", "post", "patch", "head", "options"]
    ordering_fields = [
        "priority",
        "created_at",
        "updated_at",
        "order_in_milestone",
        "order_in_priority",
    ]
    ordering = ["priority", "-is_highlighted", "order_in_milestone", "-created_at"]

    def get_queryset(self):
        # comment_count is an annotation rather than a prefetch+count so
        # large comment threads don't pull every row into memory just to
        # serialize a number. references_from/to prefetches carry a
        # select_related on the opposite side so IssueSerializer can walk
        # each edge without lazy-loading the summary fields.
        return (
            Issue.objects.select_related("milestone")
            .annotate(comment_count=Count("comments"))
            .prefetch_related(
                "github_refs",
                Prefetch(
                    "references_from",
                    queryset=IssueReference.objects.select_related("to_issue"),
                ),
                Prefetch(
                    "references_to",
                    queryset=IssueReference.objects.select_related("from_issue"),
                ),
            )
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["actor"] = _actor(self.request)
        return context

    def partial_update(self, request, *args, **kwargs):
        if "status" in request.data:
            raise ValidationError(
                {"status": "status changes go through /issues/<n>/<action>/"}
            )
        return super().partial_update(request, *args, **kwargs)

    def _transition(self, request, number, new_status):
        issue = get_object_or_404(self.get_queryset(), number=number)
        payload = StatusActionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        if new_status == Status.BLOCKED:
            reason = payload.validated_data.get("blocked_reason", "")
            if not reason:
                raise ValidationError(
                    {"blocked_reason": "required when moving to blocked"}
                )
            issue.blocked_reason = reason
        elif issue.status == Status.BLOCKED:
            issue.blocked_reason = ""
        issue.status = new_status
        # BaseModel.save splits status changes out via Issue._split_change_actions,
        # so this one save() emits both ".status.<new>" and an ".update" entry if
        # anything else changed (e.g. blocked_reason).
        issue.save(actor=_actor(request))
        return Response(IssueSerializer(issue).data)

    @action(detail=True, methods=["post"])
    def open(self, request, number=None):
        return self._transition(request, number, Status.OPEN)

    @action(detail=True, methods=["post"])
    def wip(self, request, number=None):
        return self._transition(request, number, Status.WIP)

    @action(detail=True, methods=["post"])
    def blocked(self, request, number=None):
        return self._transition(request, number, Status.BLOCKED)

    @action(detail=True, methods=["post"])
    def completed(self, request, number=None):
        return self._transition(request, number, Status.COMPLETED)

    @action(detail=True, methods=["post"])
    def wontfix(self, request, number=None):
        return self._transition(request, number, Status.WONTFIX)

    @action(detail=True, methods=["post"])
    def draft(self, request, number=None):
        return self._transition(request, number, Status.DRAFT)


class MilestoneViewSet(viewsets.ModelViewSet):
    serializer_class = MilestoneSerializer
    queryset = Milestone.objects.all()
    lookup_field = "slug"
    http_method_names = ["get", "post", "patch", "head", "options"]


class IssueCommentsView(ListModelMixin, CreateModelMixin, GenericAPIView):
    serializer_class = CommentSerializer
    pagination_class = ChronologicalCursorPagination

    def get_queryset(self):
        return Comment.objects.filter(issue__number=self.kwargs["number"])

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["actor"] = _actor(self.request)
        return context

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    def perform_create(self, serializer):
        issue = get_object_or_404(Issue, number=self.kwargs["number"])
        serializer.save(issue=issue, author=_actor(self.request))


class CommentEditView(APIView):
    """PATCH-only endpoint to edit a comment's body.

    Deletes are intentionally absent — PLAN.md says edits generate ActivityLog
    entries with a diff, while deletes would destroy history that the single
    user (and automation) rely on.
    """

    http_method_names = ["patch", "options", "head"]

    def patch(self, request, pk):
        comment = get_object_or_404(Comment, pk=pk)
        serializer = CommentSerializer(
            comment,
            data=request.data,
            partial=True,
            context={"actor": _actor(request), "request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class IssueGithubRefsView(CreateModelMixin, GenericAPIView):
    serializer_class = GithubRefSerializer

    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)

    def perform_create(self, serializer):
        issue = get_object_or_404(Issue, number=self.kwargs["number"])
        serializer.save(issue=issue)


class IssueGithubRefDeleteView(DestroyModelMixin, GenericAPIView):
    def get_queryset(self):
        return GithubRef.objects.filter(issue__number=self.kwargs["number"])

    def delete(self, request, *args, **kwargs):
        return self.destroy(request, *args, **kwargs)


class IssueReferencesView(APIView):
    """Create a cross-reference from this issue to another. Idempotent.

    If either direction already exists (A→B or B→A) we return that row rather
    than creating a duplicate — the UI treats references as symmetric.
    """

    def post(self, request, number):
        from_issue = get_object_or_404(Issue, number=number)
        payload = IssueReferenceCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        to_issue = payload.validated_data["to_issue"]
        if to_issue.pk == from_issue.pk:
            raise ValidationError({"to_issue": "cannot reference self"})
        existing = IssueReference.objects.filter(
            Q(from_issue=from_issue, to_issue=to_issue)
            | Q(from_issue=to_issue, to_issue=from_issue)
        ).first()
        if existing:
            return Response(
                {"id": existing.pk, "to_issue": to_issue.number},
                status=http_status.HTTP_200_OK,
            )
        ref = IssueReference.objects.create(from_issue=from_issue, to_issue=to_issue)
        return Response(
            {"id": ref.pk, "to_issue": to_issue.number},
            status=http_status.HTTP_201_CREATED,
        )


class IssueReferenceDeleteView(APIView):
    http_method_names = ["delete", "options", "head"]

    def delete(self, request, number, pk):
        ref = get_object_or_404(IssueReference, pk=pk)
        issue = get_object_or_404(Issue, number=number)
        if ref.from_issue_id != issue.pk and ref.to_issue_id != issue.pk:
            return Response(status=http_status.HTTP_404_NOT_FOUND)
        ref.delete()
        return Response(status=http_status.HTTP_204_NO_CONTENT)


class ActivityLogView(ListModelMixin, GenericAPIView):
    serializer_class = ActivityLogSerializer
    filterset_class = ActivityLogFilter
    pagination_class = TimestampCursorPagination

    def get_queryset(self):
        return ActivityLog.objects.select_related("content_type")

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        serializer = ActivityLogCreateSerializer(
            data=request.data, context={"actor": _actor(request)}
        )
        serializer.is_valid(raise_exception=True)
        log = serializer.save()
        return Response(
            ActivityLogSerializer(log).data, status=http_status.HTTP_201_CREATED
        )


class RenderView(APIView):
    """Markdown preview endpoint used by the htmx detail-view edit flow."""

    def post(self, request):
        serializer = RenderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        html = render_markdown(serializer.validated_data["text"])
        return Response({"html": str(html)})

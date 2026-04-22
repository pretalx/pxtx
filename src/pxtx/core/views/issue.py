from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView
from django.views.generic.edit import CreateView, UpdateView

from pxtx.core.forms import CommentForm, DescriptionForm, IssueForm
from pxtx.core.models import (
    ActivityLog,
    Comment,
    Issue,
    IssueReference,
    Milestone,
    Priority,
    Source,
    Status,
)
from pxtx.core.text import render_markdown
from pxtx.core.views._helpers import is_htmx, request_actor

QUICK_FILTERS = [
    {
        "label": "★ highlighted",
        "query": [("is_highlighted", "on")],
        "filter": {"is_highlighted": True},
    },
    {
        "label": "🔥 want",
        "query": [("priority", "1")],
        "filter": {"priority": Priority.WANT},
    },
    {"label": "🔧 wip", "query": [("status", "wip")], "filter": {"status": Status.WIP}},
    {
        "label": "🚧 blocked",
        "query": [("status", "blocked")],
        "filter": {"status": Status.BLOCKED},
    },
    {
        "label": "📥 draft",
        "query": [("status", "draft")],
        "filter": {"status": Status.DRAFT},
    },
]

DEFAULT_STATUSES = [Status.OPEN.value, Status.WIP.value, Status.BLOCKED.value]

SORT_ORDERS = {
    "priority": ("priority", "-is_highlighted", "order_in_priority", "-created_at"),
    "updated": ("-updated_at",),
    "created": ("-created_at",),
    "milestone": ("milestone__name", "order_in_milestone"),
}


def _filtered_issues(params):
    qs = Issue.objects.select_related("milestone")

    statuses = params.getlist("status")
    if not statuses and "status" not in params:
        statuses = list(DEFAULT_STATUSES)
    qs = qs.filter(status__in=statuses)

    priorities = params.getlist("priority")
    if priorities:
        qs = qs.filter(priority__in=[int(p) for p in priorities])

    milestone = params.get("milestone")
    if milestone == "null":
        qs = qs.filter(milestone__isnull=True)
    elif milestone:
        qs = qs.filter(milestone__slug=milestone)

    assignee = params.get("assignee", "").strip()
    if assignee:
        qs = qs.filter(assignee__icontains=assignee)

    sources = params.getlist("source")
    if sources:
        qs = qs.filter(source__in=sources)

    if params.get("is_highlighted") == "on":
        qs = qs.filter(is_highlighted=True)

    search = params.get("search", "").strip()
    if search:
        qs = qs.filter(
            Q(title__icontains=search)
            | Q(description__icontains=search)
            | Q(comments__body__icontains=search)
        ).distinct()

    order = SORT_ORDERS.get(params.get("sort"), SORT_ORDERS["priority"])
    return qs.order_by(*order)


def _quick_filter_active(spec, params):
    """A quick filter is "active" when every ``(key, value)`` in its query is
    present in the currently-applied params. Multi-valued params match if the
    expected value is one of the selected values."""
    return all(value in params.getlist(key) for key, value in spec["query"])


def _issue_list_context(params):
    sort = params.get("sort") or "priority"
    quick_filters = []
    for spec in QUICK_FILTERS:
        if not Issue.objects.filter(**spec["filter"]).exists():
            continue
        quick_filters.append(
            {
                "label": spec["label"],
                "querystring": spec["query"],
                "active": _quick_filter_active(spec, params),
            }
        )
    return {
        "issues": _filtered_issues(params),
        "selected_statuses": (
            params.getlist("status") if "status" in params else list(DEFAULT_STATUSES)
        ),
        "selected_priorities": params.getlist("priority"),
        "selected_sources": params.getlist("source"),
        "selected_milestone": params.get("milestone", ""),
        "search_value": params.get("search", ""),
        "assignee_value": params.get("assignee", ""),
        "highlighted_only": params.get("is_highlighted") == "on",
        "sort": sort,
        "can_reorder": sort == "priority",
        "status_choices": Status.choices,
        "priority_choices": Priority.choices,
        "source_choices": Source.choices,
        "milestones": list(Milestone.objects.order_by("-target_date", "name")),
        "quick_filters": quick_filters,
    }


@login_required
def dashboard(request):
    """Landing page: highlighted issues, work in progress, and recently
    updated issues. Anything closed is filtered out of the first two sections
    but recent updates include everything so the timeline stays honest."""
    open_statuses = [Status.OPEN.value, Status.WIP.value, Status.BLOCKED.value]
    base = Issue.objects.select_related("milestone")
    highlighted = list(
        base.filter(is_highlighted=True, status__in=open_statuses).order_by(
            "priority", "-updated_at"
        )[:10]
    )
    wip_qs = base.filter(status=Status.WIP.value).order_by("priority", "-updated_at")
    blocked_qs = base.filter(status=Status.BLOCKED.value).order_by(
        "priority", "-updated_at"
    )
    wip = list(wip_qs[:20])
    blocked = list(blocked_qs[:20])
    drafts = list(base.filter(status=Status.DRAFT.value).order_by("-updated_at")[:5])
    recent = list(base.exclude(status=Status.DRAFT.value).order_by("-updated_at")[:10])
    counts = {
        "open": Issue.objects.filter(status=Status.OPEN.value).count(),
        "wip": wip_qs.count(),
        "blocked": blocked_qs.count(),
        "draft": Issue.objects.filter(status=Status.DRAFT.value).count(),
    }
    return render(
        request,
        "core/dashboard.html",
        {
            "highlighted": highlighted,
            "wip": wip,
            "blocked": blocked,
            "drafts": drafts,
            "recent": recent,
            "counts": counts,
        },
    )


class IssueListView(LoginRequiredMixin, ListView):
    model = Issue
    template_name = "core/issue_list.html"
    context_object_name = "issues"

    def get(self, request, *args, **kwargs):
        template = "core/_issue_table.html" if is_htmx(request) else self.template_name
        return render(request, template, _issue_list_context(request.GET))


class IssueDetailView(LoginRequiredMixin, DetailView):
    model = Issue
    template_name = "core/issue_detail.html"
    context_object_name = "issue"
    slug_field = "number"
    slug_url_kwarg = "number"

    def get_queryset(self):
        return Issue.objects.select_related("milestone")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        issue = self.object
        ctx["github_refs"] = list(issue.github_refs.all())
        ctx["comments"] = list(issue.comments.all())
        ctx["comment_form"] = CommentForm()

        refs = IssueReference.objects.filter(
            Q(from_issue=issue) | Q(to_issue=issue)
        ).select_related("from_issue", "to_issue")
        related = []
        seen = set()
        for ref in refs:
            other = ref.to_issue if ref.from_issue_id == issue.pk else ref.from_issue
            if other.pk in seen:
                continue
            seen.add(other.pk)
            related.append(other)
        ctx["related_issues"] = related

        ctx["activity"] = list(
            ActivityLog.objects.filter(
                content_type=ContentType.objects.get_for_model(Issue),
                object_id=issue.pk,
            ).order_by("-timestamp")
        )
        return ctx


class _IssueFormMixin:
    model = Issue
    form_class = IssueForm
    template_name = "core/issue_form.html"

    def form_valid(self, form):
        self.object = form.save(commit=False)
        self.object.save(actor=request_actor(self.request))
        return redirect(self.object.get_absolute_url())

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["blocked_reason_visible"] = ctx["form"]["status"].value() == Status.BLOCKED
        return ctx


class IssueCreateView(LoginRequiredMixin, _IssueFormMixin, CreateView):
    def get_initial(self):
        return {
            "priority": Priority.COULD,
            "status": Status.OPEN,
            "source": Source.MANUAL,
        }

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = "New issue"
        ctx["submit_label"] = "Create issue"
        return ctx


class IssueUpdateView(LoginRequiredMixin, _IssueFormMixin, UpdateView):
    slug_field = "number"
    slug_url_kwarg = "number"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["form_title"] = f"Edit {self.object.slug}"
        ctx["submit_label"] = "Save changes"
        return ctx


class IssueHighlightToggleView(LoginRequiredMixin, View):
    def post(self, request, number):
        issue = get_object_or_404(Issue, number=number)
        issue.is_highlighted = not issue.is_highlighted
        issue.save(actor=request_actor(request))
        if is_htmx(request):
            return render(request, "core/_highlight_toggle.html", {"issue": issue})
        return redirect(issue.get_absolute_url())


class IssueDescriptionEditView(LoginRequiredMixin, View):
    def get(self, request, number):
        issue = get_object_or_404(Issue, number=number)
        form = DescriptionForm(instance=issue)
        return render(
            request, "core/_description_form.html", {"issue": issue, "form": form}
        )

    def post(self, request, number):
        issue = get_object_or_404(Issue, number=number)
        form = DescriptionForm(request.POST, instance=issue)
        form.is_valid()  # DescriptionForm has no validation errors to surface.
        issue = form.save(commit=False)
        issue.save(actor=request_actor(request))
        return render(request, "core/_description_view.html", {"issue": issue})


class IssueReorderView(LoginRequiredMixin, View):
    """Move an issue up or down within its priority bucket, then re-render
    the table. order_in_priority is rewritten densely (0..N-1) so subsequent
    reorders stay stable."""

    def post(self, request, number):
        direction = request.POST.get("direction")
        if direction not in {"up", "down"}:
            return HttpResponseBadRequest("direction must be up or down")
        issue = get_object_or_404(Issue, number=number)
        siblings = list(
            Issue.objects.filter(priority=issue.priority).order_by(
                "order_in_priority", "-created_at"
            )
        )
        index = next(i for i, s in enumerate(siblings) if s.pk == issue.pk)
        target = index - 1 if direction == "up" else index + 1
        if 0 <= target < len(siblings):
            siblings[index], siblings[target] = siblings[target], siblings[index]
            with transaction.atomic():
                for position, sibling in enumerate(siblings):
                    if sibling.order_in_priority != position:
                        sibling.order_in_priority = position
                        sibling.save(actor=request_actor(request), skip_log=True)
        # Respond with the re-rendered table so htmx can swap it in place.
        return render(
            request, "core/_issue_table.html", _issue_list_context(request.GET)
        )


class CommentCreateView(LoginRequiredMixin, View):
    def post(self, request, number):
        issue = get_object_or_404(Issue, number=number)
        form = CommentForm(request.POST)
        if form.is_valid():
            comment = form.save(commit=False)
            comment.issue = issue
            comment.author = request_actor(request)
            comment.save(actor=request_actor(request))
            form = CommentForm()
        return render(
            request,
            "core/_comments_section.html",
            {
                "issue": issue,
                "comment_form": form,
                "comments": list(issue.comments.all()),
            },
        )


class CommentEditView(LoginRequiredMixin, View):
    def get(self, request, pk):
        comment = get_object_or_404(Comment, pk=pk)
        return render(
            request,
            "core/_comment_form.html",
            {"comment": comment, "form": CommentForm(instance=comment)},
        )

    def post(self, request, pk):
        comment = get_object_or_404(Comment, pk=pk)
        form = CommentForm(request.POST, instance=comment)
        if not form.is_valid():
            return render(
                request, "core/_comment_form.html", {"comment": comment, "form": form}
            )
        comment = form.save(commit=False)
        comment.edited_at = timezone.now()
        comment.save(actor=request_actor(request))
        return render(request, "core/_comment.html", {"comment": comment})


@login_required
@require_POST
def render_markdown_preview(request):
    html = render_markdown(request.POST.get("text", ""))
    return HttpResponse(html)


@login_required
def blocked_reason_field(request):
    """Return the blocked_reason form field, shown only when status=blocked."""
    form = IssueForm()
    return render(
        request,
        "core/_blocked_reason.html",
        {
            "field": form["blocked_reason"],
            "show": request.GET.get("status") == Status.BLOCKED,
        },
    )

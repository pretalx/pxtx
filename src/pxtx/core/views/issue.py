from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView
from django.views.generic.edit import CreateView, UpdateView

from pxtx.core.forms import CommentForm, DescriptionForm, IssueForm
from pxtx.core.models import (
    ActivityLog,
    Comment,
    Effort,
    Issue,
    IssueReference,
    Milestone,
    Priority,
    Source,
    Status,
)
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

SORT_COLUMNS = {
    "priority": {
        "label": "Priority",
        "default": "asc",
        "asc": ("priority", "-is_highlighted", "order_in_priority", "-created_at"),
        "desc": ("-priority", "-is_highlighted", "order_in_priority", "-created_at"),
    },
    "number": {
        "label": "Issue",
        "default": "desc",
        "asc": ("number",),
        "desc": ("-number",),
    },
    "title": {
        "label": "Title",
        "default": "asc",
        "asc": ("title",),
        "desc": ("-title",),
    },
    "status": {
        "label": "Status",
        "default": "asc",
        "asc": ("status",),
        "desc": ("-status",),
    },
    "effort": {
        "label": "Effort",
        "default": "asc",
        "asc": ("effort_minutes",),
        "desc": ("-effort_minutes",),
    },
    "assignee": {
        "label": "Assignee",
        "default": "asc",
        "asc": ("assignee",),
        "desc": ("-assignee",),
    },
    "milestone": {
        "label": "Release",
        "default": "asc",
        "asc": ("milestone__name", "order_in_milestone"),
        "desc": ("-milestone__name", "order_in_milestone"),
    },
    "updated": {
        "label": "Updated",
        "default": "desc",
        "asc": ("updated_at",),
        "desc": ("-updated_at",),
    },
}

# Order the table columns render in, so the template can look up by key.
SORT_HEADER_ORDER = (
    "number",
    "title",
    "status",
    "priority",
    "effort",
    "assignee",
    "milestone",
    "updated",
)


def _resolve_sort(params):
    sort = params.get("sort") or "priority"
    if sort not in SORT_COLUMNS:
        sort = "priority"
    direction = params.get("dir")
    if direction not in {"asc", "desc"}:
        direction = SORT_COLUMNS[sort]["default"]
    return sort, direction


def _sort_headers(params, sort, direction):
    base = params.copy()
    base.pop("sort", None)
    base.pop("dir", None)
    headers = {}
    for column in SORT_HEADER_ORDER:
        spec = SORT_COLUMNS[column]
        is_active = column == sort
        if is_active:
            next_direction = "desc" if direction == "asc" else "asc"
        else:
            next_direction = spec["default"]
        query = base.copy()
        query["sort"] = column
        query["dir"] = next_direction
        headers[column] = {
            "label": spec["label"],
            "active": is_active,
            "direction": direction if is_active else "",
            "querystring": query.urlencode(),
        }
    return headers


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

    if params.get("is_highlighted") == "on":
        qs = qs.filter(is_highlighted=True)

    search = params.get("search", "").strip()
    if search:
        qs = qs.filter(
            Q(title__icontains=search)
            | Q(description__icontains=search)
            | Q(comments__body__icontains=search)
        ).distinct()

    sort, direction = _resolve_sort(params)
    return qs.order_by(*SORT_COLUMNS[sort][direction])


def _quick_filter_active(spec, params):
    """A quick filter is "active" when every ``(key, value)`` in its query is
    present in the currently-applied params. Multi-valued params match if the
    expected value is one of the selected values."""
    return all(value in params.getlist(key) for key, value in spec["query"])


def _issue_list_context(params):
    sort, direction = _resolve_sort(params)
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
        "selected_milestone": params.get("milestone", ""),
        "search_value": params.get("search", ""),
        "assignee_value": params.get("assignee", ""),
        "highlighted_only": params.get("is_highlighted") == "on",
        "sort": sort,
        "direction": direction,
        "sort_headers": _sort_headers(params, sort, direction),
        "can_reorder": sort == "priority" and direction == "asc",
        "status_choices": Status.choices,
        "priority_choices": Priority.choices,
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


class IssueModalEditView(LoginRequiredMixin, View):
    """Modal-friendly edit endpoint for the list and kanban views. GET returns
    the form fragment (no chrome) so htmx can drop it into the dialog. POST
    saves and answers 204 + ``HX-Trigger: pxtx:issue-saved`` on success — the
    client closes the dialog and refreshes whichever container it came from.
    Validation errors rerender the fragment so the dialog stays open with
    messages in place."""

    def _context(self, issue, form):
        return {
            "form": form,
            "issue": issue,
            "blocked_reason_visible": (form["status"].value() == Status.BLOCKED),
        }

    def get(self, request, number):
        issue = get_object_or_404(Issue, number=number)
        form = IssueForm(instance=issue)
        return render(
            request, "core/_issue_modal_form.html", self._context(issue, form)
        )

    def post(self, request, number):
        issue = get_object_or_404(Issue, number=number)
        form = IssueForm(request.POST, instance=issue)
        if not form.is_valid():
            return render(
                request, "core/_issue_modal_form.html", self._context(issue, form)
            )
        issue = form.save(commit=False)
        issue.save(actor=request_actor(request))
        response = HttpResponse(status=204)
        response["HX-Trigger"] = "pxtx:issue-saved"
        return response


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
    """Drop an issue at a given index within its priority bucket, then
    re-render the table. Sibling ordering matches the display sort
    (``-is_highlighted, order_in_priority, -created_at``) so the client's
    drop index maps to what the user sees. ``order_in_priority`` is rewritten
    densely (0..N-1) via ``bulk_update`` so subsequent reorders stay stable
    and no ActivityLog entries are produced."""

    def post(self, request, number):
        index_raw = request.POST.get("index")
        if index_raw is None:
            return HttpResponseBadRequest("index is required")
        try:
            index = int(index_raw)
        except ValueError:
            return HttpResponseBadRequest("index must be an integer")
        issue = get_object_or_404(Issue, number=number)
        siblings = list(
            Issue.objects.filter(priority=issue.priority)
            .exclude(pk=issue.pk)
            .order_by("-is_highlighted", "order_in_priority", "-created_at")
        )
        index = max(0, min(index, len(siblings)))
        siblings.insert(index, issue)
        # Highlighted issues are the primary in-bucket sort key on the list,
        # so a non-highlighted drop into the highlighted band (or vice-versa)
        # would snap back on re-render. A stable sort by ``-is_highlighted``
        # keeps the user's intra-group order while enforcing that invariant
        # in the stored ``order_in_priority``.
        siblings.sort(key=lambda s: 0 if s.is_highlighted else 1)
        updates = []
        for position, sibling in enumerate(siblings):
            if sibling.order_in_priority != position:
                sibling.order_in_priority = position
                updates.append(sibling)
        if updates:
            with transaction.atomic():
                Issue.objects.bulk_update(updates, ["order_in_priority"])
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


INLINE_CELL_FIELDS = {
    "status": {"attr": "status", "choices": list(Status.choices), "cast": str},
    "priority": {"attr": "priority", "choices": list(Priority.choices), "cast": int},
    "effort": {
        "attr": "effort_minutes",
        "choices": [("", "—"), *Effort.choices],
        # Blank option stores NULL; any other value is a known Effort int.
        "cast": lambda raw: int(raw) if raw else None,
    },
}


def _cell_context(issue, field):
    spec = INLINE_CELL_FIELDS[field]
    current_raw = getattr(issue, spec["attr"])
    current = "" if current_raw is None else str(current_raw)
    return {
        "issue": issue,
        "field": field,
        "choices": [(str(value), label) for value, label in spec["choices"]],
        "current": current,
    }


class IssueInlineCellView(LoginRequiredMixin, View):
    """Click-to-edit list cells for status/priority/effort. GET returns a
    select element in place of the display badge; POSTing a new value saves
    the field through the normal save path (ActivityLog honored) and returns
    the re-rendered display cell. Setting ``status=blocked`` without a
    ``blocked_reason`` mirrors the kanban guard and redirects to the edit
    form via ``HX-Redirect`` instead of silently bypassing the requirement."""

    def _spec(self, field):
        return INLINE_CELL_FIELDS.get(field)

    def get(self, request, number, field):
        if self._spec(field) is None:
            return HttpResponseBadRequest("unknown field")
        issue = get_object_or_404(Issue, number=number)
        ctx = {**_cell_context(issue, field), "editing": True}
        return render(request, "core/_issue_cell.html", ctx)

    def post(self, request, number, field):
        spec = self._spec(field)
        if spec is None:
            return HttpResponseBadRequest("unknown field")
        issue = get_object_or_404(Issue, number=number)
        raw = request.POST.get("value", "")
        allowed = {str(value) for value, _ in spec["choices"]}
        if raw not in allowed:
            return HttpResponseBadRequest("invalid value")
        value = spec["cast"](raw)
        if (
            field == "status"
            and value == Status.BLOCKED.value
            and issue.status != Status.BLOCKED.value
            and not issue.blocked_reason
        ):
            response = HttpResponse(status=204)
            response["HX-Redirect"] = reverse(
                "core:issue-edit", kwargs={"number": issue.number}
            )
            return response
        setattr(issue, spec["attr"], value)
        issue.save(actor=request_actor(request))
        ctx = {**_cell_context(issue, field), "editing": False}
        return render(request, "core/_issue_cell.html", ctx)


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

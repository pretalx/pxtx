from django.conf import settings
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

from pxtx.core.forms import CommentForm, DescriptionForm, IssueFilterForm, IssueForm
from pxtx.core.models import (
    ActivityLog,
    Comment,
    Effort,
    GithubRef,
    GithubRefKind,
    Issue,
    IssueReference,
    Milestone,
    Priority,
    Source,
    Status,
)
from pxtx.core.views._helpers import is_htmx, request_actor
from pxtx.core.widgets import EnhancedSelect

QUICK_FILTERS = [
    {
        "label": "★ highlighted",
        "query": [("is_highlighted", "on")],
        "filter": {"is_highlighted": True},
    },
    {
        "label": "🔥 jetzt",
        "query": [("priority", "0")],
        "filter": {"priority": Priority.JETZT},
    },
    {
        "label": "💪 will",
        "query": [("priority", "1")],
        "filter": {"priority": Priority.WILL},
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
        query = (
            Q(title__icontains=search)
            | Q(description__icontains=search)
            | Q(comments__body__icontains=search)
        )
        if search.isdigit():
            query |= Q(number=int(search))
        qs = qs.filter(query).distinct()

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
    selected_statuses = (
        params.getlist("status") if "status" in params else list(DEFAULT_STATUSES)
    )
    selected_priorities = params.getlist("priority")
    return {
        "issues": _filtered_issues(params),
        "selected_statuses": selected_statuses,
        "selected_priorities": selected_priorities,
        "selected_milestone": params.get("milestone", ""),
        "search_value": params.get("search", ""),
        "assignee_value": params.get("assignee", ""),
        "highlighted_only": params.get("is_highlighted") == "on",
        "sort": sort,
        "direction": direction,
        "sort_headers": _sort_headers(params, sort, direction),
        "can_reorder": sort == "priority" and direction == "asc",
        "filter_form": IssueFilterForm(
            initial={"status": selected_statuses, "priority": selected_priorities}
        ),
        "milestones": list(Milestone.objects.order_by("-target_date", "name")),
        "quick_filters": quick_filters,
    }


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
        ctx["comments"] = list(issue.comments.all())
        ctx["comment_form"] = CommentForm()
        ctx.update(_detail_sections_context(issue))

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


CREATE_DEFAULTS = {
    "priority": Priority.KOENNTE,
    "status": Status.OPEN,
    "source": Source.MANUAL,
}


class IssueCreateView(LoginRequiredMixin, _IssueFormMixin, CreateView):
    def get_initial(self):
        return dict(CREATE_DEFAULTS)

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
    the form fragment (no chrome) so htmx can drop it into the dialog. In
    sidebar mode (``?mode=sidebar``, used by the issue list side panel) the
    form is rendered without a submit button and auto-saves on field changes;
    POST answers 204 + ``HX-Trigger: pxtx:issue-autosaved`` so the list
    refreshes but the sidebar stays open. In modal mode POST answers 204 +
    ``HX-Trigger: pxtx:issue-saved`` so the client closes the dialog and
    refreshes the container. Validation errors rerender the fragment in
    either case."""

    def _context(self, issue, form, *, sidebar_mode=False):
        return {
            "form": form,
            "issue": issue,
            "form_action": reverse(
                "core:issue-modal-edit", kwargs={"number": issue.number}
            )
            + ("?mode=sidebar" if sidebar_mode else ""),
            "modal_target": "issue-modal",
            "submit_label": "Save changes",
            "blocked_reason_visible": (form["status"].value() == Status.BLOCKED),
            "sidebar_mode": sidebar_mode,
        }

    def get(self, request, number):
        issue = get_object_or_404(Issue, number=number)
        form = IssueForm(instance=issue)
        sidebar_mode = request.GET.get("mode") == "sidebar"
        return render(
            request,
            "core/_issue_modal_form.html",
            self._context(issue, form, sidebar_mode=sidebar_mode),
        )

    def post(self, request, number):
        issue = get_object_or_404(Issue, number=number)
        sidebar_mode = request.GET.get("mode") == "sidebar"
        form = IssueForm(request.POST, instance=issue)
        if not form.is_valid():
            return render(
                request,
                "core/_issue_modal_form.html",
                self._context(issue, form, sidebar_mode=sidebar_mode),
            )
        issue = form.save(commit=False)
        issue.save(actor=request_actor(request))
        response = HttpResponse(status=204)
        response["HX-Trigger"] = (
            "pxtx:issue-autosaved" if sidebar_mode else "pxtx:issue-saved"
        )
        return response


class IssueModalCreateView(LoginRequiredMixin, View):
    """Modal-friendly create endpoint. GET returns the form fragment pre-filled
    with sensible defaults so htmx can drop it into ``#issue-create-modal``.
    POST creates the issue and answers 204 + ``HX-Redirect`` to the new issue
    detail page on success; validation errors rerender the fragment so the
    dialog stays open."""

    def _context(self, form):
        return {
            "form": form,
            "issue": None,
            "form_action": reverse("core:issue-modal-new"),
            "modal_target": "issue-create-modal",
            "submit_label": "Create issue",
            "blocked_reason_visible": (form["status"].value() == Status.BLOCKED),
        }

    def get(self, request):
        form = IssueForm(initial=dict(CREATE_DEFAULTS))
        return render(request, "core/_issue_modal_form.html", self._context(form))

    def post(self, request):
        form = IssueForm(request.POST)
        if not form.is_valid():
            return render(request, "core/_issue_modal_form.html", self._context(form))
        issue = form.save(commit=False)
        issue.save(actor=request_actor(request))
        response = HttpResponse(status=204)
        response["HX-Redirect"] = issue.get_absolute_url()
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
    cell_url = reverse(
        "core:issue-cell", kwargs={"number": issue.number, "field": field}
    )
    widget = EnhancedSelect(
        badge_type=field,
        inline_edit=True,
        attrs={
            "hx-post": cell_url,
            "hx-trigger": "change",
            "hx-target": "closest td",
            "hx-swap": "outerHTML",
            "data-revert-url": cell_url,
            "aria-label": field,
            "autofocus": True,
        },
    )
    widget.choices = [(str(value), label) for value, label in spec["choices"]]
    return {
        "issue": issue,
        "field": field,
        "cell_select": widget.render("value", current),
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


# Sidebar add-and-remove sections on the issue detail view: links,
# interested parties, GitHub refs, and related issues. Each section is its
# own template fragment extending ``_issue_sidebar_section.html``; the
# "+ Add" button toggles the inline add form via htmx (``?form=1``) and
# submit/delete swap the whole section back in place.

# (section_id, url_name) keyed by the short section name used in _render_section.
_SECTION_META = {
    "links": ("issue-links", "core:issue-links"),
    "parties": ("issue-parties", "core:issue-parties"),
    "github_refs": ("issue-github-refs", "core:issue-github-refs"),
    "related": ("issue-related", "core:issue-related"),
}


def _related_issues(issue):
    """Distinct list of issues referenced from or to this issue. Each issue
    is annotated with a ``ref_id`` attribute pointing at the IssueReference
    row to delete when the user unlinks (the first one we see in either
    direction — symmetric duplicates are not normally created)."""
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
        other.ref_id = ref.pk
        related.append(other)
    return related


def _other_issues(issue):
    return list(
        Issue.objects.exclude(pk=issue.pk).only("number", "title").order_by("number")
    )


def _links_ctx(issue):
    return {"links": list(issue.links or [])}


def _parties_ctx(issue):
    return {"parties": list(issue.interested_parties or [])}


def _github_refs_ctx(issue):
    return {
        "github_refs": list(issue.github_refs.all()),
        "github_ref_kinds": list(GithubRefKind.choices),
        "default_github_repo": settings.DEFAULT_GITHUB_REPO,
    }


def _related_ctx(issue):
    return {
        "related_issues": _related_issues(issue),
        "other_issues": _other_issues(issue),
    }


_SECTION_CONTEXT = {
    "links": _links_ctx,
    "parties": _parties_ctx,
    "github_refs": _github_refs_ctx,
    "related": _related_ctx,
}


def _detail_sections_context(issue):
    """Context for the initial full-page render: union of all four sections."""
    ctx = {}
    for builder in _SECTION_CONTEXT.values():
        ctx.update(builder(issue))
    return ctx


def _render_section(request, issue, name, *, adding=False, error=None, draft=None):
    section_id, section_url_name = _SECTION_META[name]
    ctx = _SECTION_CONTEXT[name](issue)
    ctx.update(
        {
            "issue": issue,
            "section_id": section_id,
            "section_url_name": section_url_name,
            "adding": adding,
            "error": error,
            "draft": draft or {},
        }
    )
    return render(request, f"core/_issue_{name}.html", ctx)


def _form_error(request, issue, name, error, draft):
    return _render_section(request, issue, name, adding=True, error=error, draft=draft)


class _SectionView(LoginRequiredMixin, View):
    section_name = ""

    def get(self, request, number):
        issue = get_object_or_404(Issue, number=number)
        adding = request.GET.get("form") == "1"
        return _render_section(request, issue, self.section_name, adding=adding)


class _JsonListDeleteView(LoginRequiredMixin, View):
    """Shared delete-by-index for sections backed by an Issue JSON-list field."""

    section_name = ""
    attr_name = ""

    def post(self, request, number, index):
        issue = get_object_or_404(Issue, number=number)
        items = list(getattr(issue, self.attr_name) or [])
        if 0 <= index < len(items):
            del items[index]
            setattr(issue, self.attr_name, items)
            issue.save(actor=request_actor(request))
        return _render_section(request, issue, self.section_name)


class IssueLinksView(_SectionView):
    section_name = "links"

    def post(self, request, number):
        issue = get_object_or_404(Issue, number=number)
        label = request.POST.get("label", "").strip()
        url = request.POST.get("url", "").strip()
        draft = {"label": label, "url": url}
        if not label or not url:
            return _form_error(
                request,
                issue,
                self.section_name,
                "Both label and URL are required.",
                draft,
            )
        issue.links = [*(issue.links or []), {"label": label, "url": url}]
        issue.save(actor=request_actor(request))
        return _render_section(request, issue, self.section_name)


class IssueLinkDeleteView(_JsonListDeleteView):
    section_name = "links"
    attr_name = "links"


class IssuePartiesView(_SectionView):
    section_name = "parties"

    def post(self, request, number):
        issue = get_object_or_404(Issue, number=number)
        label = request.POST.get("label", "").strip()
        url = request.POST.get("url", "").strip()
        note = request.POST.get("note", "").strip()
        draft = {"label": label, "url": url, "note": note}
        if not label:
            return _form_error(
                request, issue, self.section_name, "Label is required.", draft
            )
        entry = {"label": label}
        if url:
            entry["url"] = url
        if note:
            entry["note"] = note
        issue.interested_parties = [*(issue.interested_parties or []), entry]
        issue.save(actor=request_actor(request))
        return _render_section(request, issue, self.section_name)


class IssuePartyDeleteView(_JsonListDeleteView):
    section_name = "parties"
    attr_name = "interested_parties"


def _github_ref_log_data(ref):
    return {"kind": ref.kind, "repo": ref.repo, "number": ref.number, "sha": ref.sha}


class IssueGithubRefsView(_SectionView):
    section_name = "github_refs"

    def post(self, request, number):
        issue = get_object_or_404(Issue, number=number)
        kind = request.POST.get("kind", "").strip()
        repo = request.POST.get("repo", "").strip() or settings.DEFAULT_GITHUB_REPO
        ref_number_raw = request.POST.get("number", "").strip()
        sha = request.POST.get("sha", "").strip()
        draft = {"kind": kind, "repo": repo, "number": ref_number_raw, "sha": sha}
        valid_kinds = {value for value, _ in GithubRefKind.choices}
        if kind not in valid_kinds:
            return _form_error(request, issue, self.section_name, "Pick a kind.", draft)
        if kind == GithubRefKind.COMMIT:
            if not sha:
                return _form_error(
                    request, issue, self.section_name, "Commit SHA is required.", draft
                )
            ref, created = GithubRef.objects.get_or_create(
                issue=issue, kind=kind, repo=repo, sha=sha
            )
        else:
            try:
                ref_number = int(ref_number_raw)
            except ValueError:
                return _form_error(
                    request,
                    issue,
                    self.section_name,
                    "Issue/PR number must be an integer.",
                    draft,
                )
            ref, created = GithubRef.objects.get_or_create(
                issue=issue, kind=kind, repo=repo, number=ref_number
            )
        if created:
            issue.log_action(
                ".github_ref.added",
                actor=request_actor(request),
                data=_github_ref_log_data(ref),
            )
        return _render_section(request, issue, self.section_name)


class IssueGithubRefDeleteView(LoginRequiredMixin, View):
    def post(self, request, number, pk):
        issue = get_object_or_404(Issue, number=number)
        ref = GithubRef.objects.filter(pk=pk, issue=issue).first()
        if ref is not None:
            data = _github_ref_log_data(ref)
            ref.delete()
            issue.log_action(
                ".github_ref.removed", actor=request_actor(request), data=data
            )
        return _render_section(request, issue, "github_refs")


class IssueRelatedView(_SectionView):
    section_name = "related"

    def post(self, request, number):
        issue = get_object_or_404(Issue, number=number)
        raw = request.POST.get("target", "").strip()
        draft = {"target": raw}
        target_number = _parse_issue_number(raw)
        if target_number is None:
            return _form_error(
                request,
                issue,
                self.section_name,
                "Enter an issue number, e.g. PX-42 or 42.",
                draft,
            )
        if target_number == issue.number:
            return _form_error(
                request,
                issue,
                self.section_name,
                "An issue cannot reference itself.",
                draft,
            )
        try:
            target = Issue.objects.get(number=target_number)
        except Issue.DoesNotExist:
            return _form_error(
                request,
                issue,
                self.section_name,
                f"No issue PX-{target_number}.",
                draft,
            )
        existing = IssueReference.objects.filter(
            Q(from_issue=issue, to_issue=target) | Q(from_issue=target, to_issue=issue)
        ).first()
        if existing is None:
            IssueReference.objects.create(from_issue=issue, to_issue=target)
            issue.log_action(
                ".related.added",
                actor=request_actor(request),
                data={"other_number": target.number, "other_slug": target.slug},
            )
        return _render_section(request, issue, self.section_name)


class IssueRelatedDeleteView(LoginRequiredMixin, View):
    def post(self, request, number, pk):
        issue = get_object_or_404(Issue, number=number)
        ref = (
            IssueReference.objects.filter(pk=pk)
            .select_related("from_issue", "to_issue")
            .first()
        )
        if ref is not None and issue.pk in (ref.from_issue_id, ref.to_issue_id):
            other = ref.to_issue if ref.from_issue_id == issue.pk else ref.from_issue
            ref.delete()
            issue.log_action(
                ".related.removed",
                actor=request_actor(request),
                data={"other_number": other.number, "other_slug": other.slug},
            )
        return _render_section(request, issue, "related")


def _parse_issue_number(raw):
    """Accept ``PX-42`` (case-insensitive), ``#42``, or plain ``42``."""
    if not raw:
        return None
    cleaned = raw.strip().upper()
    if cleaned.startswith("PX-"):
        cleaned = cleaned[3:]
    elif cleaned.startswith("#"):
        cleaned = cleaned[1:]
    try:
        value = int(cleaned)
    except ValueError:
        return None
    if value <= 0:
        return None
    return value

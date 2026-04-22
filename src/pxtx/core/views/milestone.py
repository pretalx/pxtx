from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views import View
from django.views.generic import DetailView, ListView

from pxtx.core.models import Issue, Milestone, Status

# Columns on the board, in display order. "done" folds completed + wontfix
# together; cross-column drops onto it become ``completed`` (wontfix is
# reachable only via the edit form). The first status in each tuple is the
# one a drop into that column writes by default.
KANBAN_COLUMNS = [
    ("open", "Open", (Status.OPEN,)),
    ("wip", "In progress", (Status.WIP,)),
    ("blocked", "Blocked", (Status.BLOCKED,)),
    ("done", "Done", (Status.COMPLETED, Status.WONTFIX)),
]

KANBAN_TARGET_STATUSES = {key: statuses[0].value for key, _, statuses in KANBAN_COLUMNS}
KANBAN_VISIBLE_STATUSES = {
    status.value for _, _, statuses in KANBAN_COLUMNS for status in statuses
}


def _actor(request):
    return f"user/{request.user.username}"


def _build_columns(milestone):
    issues = list(milestone.issues.order_by("order_in_milestone", "-created_at").all())
    columns = []
    for key, label, statuses in KANBAN_COLUMNS:
        values = {status.value for status in statuses}
        cards = [issue for issue in issues if issue.status in values]
        columns.append(
            {"key": key, "label": label, "cards": cards, "count": len(cards)}
        )
    return columns


class MilestoneListView(LoginRequiredMixin, ListView):
    model = Milestone
    template_name = "core/milestone_list.html"
    context_object_name = "milestones"

    def get_queryset(self):
        return Milestone.objects.annotate(issue_count=Count("issues"))


class MilestoneDetailView(LoginRequiredMixin, DetailView):
    model = Milestone
    template_name = "core/milestone_detail.html"
    context_object_name = "milestone"
    slug_url_kwarg = "slug"
    slug_field = "slug"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["columns"] = _build_columns(self.object)
        return ctx


class MilestoneKanbanMoveView(LoginRequiredMixin, View):
    """Accepts a drag-drop from the kanban: move an issue to a (column,
    position). Cross-column drops update status through the normal save
    path so the change is logged. Order-only drops rewrite the column's
    ``order_in_milestone`` densely via ``bulk_update``, which skips log
    entries and leaves ``updated_at`` untouched on shuffled siblings.
    Returns the re-rendered board so the client swaps it back in."""

    def post(self, request, slug):
        milestone = get_object_or_404(Milestone, slug=slug)

        number = request.POST.get("issue")
        column = request.POST.get("column")
        index_raw = request.POST.get("index")
        if not number or not column or index_raw is None:
            return HttpResponseBadRequest("issue, column, index required")
        if column not in KANBAN_TARGET_STATUSES:
            return HttpResponseBadRequest("unknown kanban column")
        try:
            number = int(number)
            index = int(index_raw)
        except ValueError:
            return HttpResponseBadRequest("issue/index must be integers")

        issue = get_object_or_404(Issue, number=number, milestone=milestone)

        # Issues not shown on the board (e.g. drafts) have no card to drag,
        # so a move request for one is necessarily a crafted POST. Reject it
        # rather than silently promoting the issue into a visible status.
        if issue.status not in KANBAN_VISIBLE_STATUSES:
            return HttpResponseBadRequest("issue is not on the kanban")

        target_status = KANBAN_TARGET_STATUSES[column]
        # The Done column is a display fold of completed + wontfix. A drop
        # inside it must not coerce wontfix -> completed.
        if column == "done" and issue.status == Status.WONTFIX.value:
            target_status = Status.WONTFIX.value
        # Moving into Blocked needs a reason — the edit form enforces this
        # and drag must not silently bypass it. Reordering within Blocked
        # (issue is already blocked) is fine.
        if (
            column == "blocked"
            and issue.status != Status.BLOCKED.value
            and not issue.blocked_reason
        ):
            return HttpResponseBadRequest(
                "moving to blocked requires a reason; use the edit form"
            )

        with transaction.atomic():
            if issue.status != target_status:
                issue.status = target_status
                issue.save(actor=_actor(request))

            # Done reorders across both completed and wontfix since the user
            # sees them as one list. Other columns reorder within their
            # single backing status.
            if column == "done":
                sibling_filter = Q(status=Status.COMPLETED.value) | Q(
                    status=Status.WONTFIX.value
                )
            else:
                sibling_filter = Q(status=target_status)
            column_issues = list(
                Issue.objects.filter(milestone=milestone)
                .filter(sibling_filter)
                .exclude(pk=issue.pk)
                .order_by("order_in_milestone", "-created_at")
            )
            index = max(0, min(index, len(column_issues)))
            column_issues.insert(index, issue)
            updates = []
            for position, item in enumerate(column_issues):
                if item.order_in_milestone != position:
                    item.order_in_milestone = position
                    updates.append(item)
            if updates:
                Issue.objects.bulk_update(updates, ["order_in_milestone"])

        return render(
            request,
            "core/_kanban_board.html",
            {"milestone": milestone, "columns": _build_columns(milestone)},
        )

import datetime as dt

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from pxtx.core.models import ActivityLog, Comment, Issue

# Heatmap configuration: 53 weeks ending today, weeks start on Sunday to
# match GitHub's contribution graph. Only issue opens and closes are counted
# — the heatmap is about visible progress, not every field edit.
HEATMAP_WEEKS = 53
HEATMAP_OPEN_ACTION = "pxtx.issue.create"
HEATMAP_CLOSE_ACTIONS = ("pxtx.issue.status.completed", "pxtx.issue.status.wontfix")

# Content types we know how to resolve to a human-facing target on the feed.
KNOWN_CONTENT_TYPES = (("issue", "Issue"), ("comment", "Comment"))

PAGE_SIZE = 50


def _htmx(request):
    return request.headers.get("HX-Request") == "true"


def _tier(count):
    """Bucket a day's event count into a GitHub-style intensity tier."""
    if count <= 0:
        return 0
    if count == 1:
        return 1
    if count <= 3:
        return 2
    if count <= 6:
        return 3
    return 4


def _heatmap_bounds():
    """First visible Sunday and today, in the active timezone."""
    today = timezone.localdate()
    # Python weekday(): Mon=0..Sun=6. Days since the most recent Sunday (0 if
    # today is Sunday) so the last column always ends at today.
    days_since_sunday = (today.weekday() + 1) % 7
    start = today - dt.timedelta(days=days_since_sunday + (HEATMAP_WEEKS - 1) * 7)
    return start, today


def _counts_by_day(action_filter, start, end):
    return dict(
        ActivityLog.objects.filter(
            action_filter, timestamp__date__gte=start, timestamp__date__lte=end
        )
        .annotate(day=TruncDate("timestamp"))
        .values("day")
        .annotate(count=Count("id"))
        .values_list("day", "count")
    )


def _build_heatmap():
    start, today = _heatmap_bounds()
    opens = _counts_by_day(Q(action_type=HEATMAP_OPEN_ACTION), start, today)
    closes = _counts_by_day(Q(action_type__in=HEATMAP_CLOSE_ACTIONS), start, today)

    cells = []
    for week in range(HEATMAP_WEEKS):
        for weekday in range(7):
            day = start + dt.timedelta(days=week * 7 + weekday)
            if day > today:
                cells.append({"empty": True})
                continue
            opened = opens.get(day, 0)
            closed = closes.get(day, 0)
            total = opened + closed
            cells.append(
                {
                    "empty": False,
                    "date": day,
                    "opened": opened,
                    "closed": closed,
                    "total": total,
                    "tier": _tier(total),
                }
            )

    return {
        "heatmap_cells": cells,
        "heatmap_start": start,
        "heatmap_end": today,
        "heatmap_total_opened": sum(opens.values()),
        "heatmap_total_closed": sum(closes.values()),
    }


def _attach_targets(entries):
    """Resolve each entry's GFK target in bulk, so rendering the list doesn't
    fan out into one query per row."""
    issue_ct = ContentType.objects.get_for_model(Issue)
    comment_ct = ContentType.objects.get_for_model(Comment)
    issue_ids = {e.object_id for e in entries if e.content_type_id == issue_ct.id}
    comment_ids = {e.object_id for e in entries if e.content_type_id == comment_ct.id}
    issues = (
        {i.pk: i for i in Issue.objects.filter(pk__in=issue_ids)} if issue_ids else {}
    )
    comments = (
        {
            c.pk: c
            for c in Comment.objects.filter(pk__in=comment_ids).select_related("issue")
        }
        if comment_ids
        else {}
    )
    for entry in entries:
        if entry.content_type_id == issue_ct.id:
            entry.target_issue = issues.get(entry.object_id)
            entry.target_comment = None
        elif entry.content_type_id == comment_ct.id:
            comment = comments.get(entry.object_id)
            entry.target_issue = comment.issue if comment else None
            entry.target_comment = comment
        else:
            entry.target_issue = None
            entry.target_comment = None


class ActivityView(LoginRequiredMixin, View):
    """Global activity feed + yearly heatmap.

    Full-page renders include the heatmap; htmx re-requests from the filter
    form swap only the list, so filter changes don't recompute the yearly
    aggregate.
    """

    template_name = "core/activity.html"
    list_template_name = "core/_activity_list.html"

    def get(self, request):
        params = request.GET
        qs = ActivityLog.objects.select_related("content_type")

        actor = params.get("actor", "").strip()
        if actor:
            qs = qs.filter(actor__icontains=actor)

        action_type = params.get("action_type", "").strip()
        if action_type:
            qs = qs.filter(action_type__icontains=action_type)

        content_type = params.get("content_type", "").strip()
        if content_type:
            qs = qs.filter(content_type__model=content_type)

        since = params.get("since", "").strip()
        if since:
            try:
                since_date = dt.date.fromisoformat(since)
            except ValueError:
                since_date = None
            if since_date is not None:
                qs = qs.filter(timestamp__date__gte=since_date)

        qs = qs.order_by("-timestamp")
        paginator = Paginator(qs, PAGE_SIZE)
        page_obj = paginator.get_page(params.get("page") or 1)
        entries = list(page_obj.object_list)
        _attach_targets(entries)

        context = {
            "entries": entries,
            "page_obj": page_obj,
            "actor_value": actor,
            "action_type_value": action_type,
            "content_type_value": content_type,
            "since_value": since,
            "content_type_choices": KNOWN_CONTENT_TYPES,
        }

        if _htmx(request):
            return render(request, self.list_template_name, context)

        context.update(_build_heatmap())
        return render(request, self.template_name, context)

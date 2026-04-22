from django.db.models import Q
from django_filters import rest_framework as filters

from pxtx.core.models import ActivityLog, Issue


class CsvCharFilter(filters.BaseInFilter, filters.CharFilter):
    """Filter like ``?status=open,wip`` into ``status__in=[open, wip]``."""


class CsvNumberFilter(filters.BaseInFilter, filters.NumberFilter):
    """Same as CsvCharFilter, for integer-choice fields like priority."""


class IssueFilter(filters.FilterSet):
    status = CsvCharFilter(field_name="status", lookup_expr="in")
    priority = CsvNumberFilter(field_name="priority", lookup_expr="in")
    milestone = filters.CharFilter(method="filter_milestone")
    assignee = filters.CharFilter(field_name="assignee", lookup_expr="icontains")
    is_highlighted = filters.BooleanFilter(field_name="is_highlighted")
    source = CsvCharFilter(field_name="source", lookup_expr="in")
    search = filters.CharFilter(method="filter_search")

    class Meta:
        model = Issue
        fields = [
            "status",
            "priority",
            "milestone",
            "assignee",
            "is_highlighted",
            "source",
        ]

    def filter_milestone(self, queryset, name, value):
        if value == "null":
            return queryset.filter(milestone__isnull=True)
        return queryset.filter(milestone__slug=value)

    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(title__icontains=value) | Q(description__icontains=value)
        )


class ActivityLogFilter(filters.FilterSet):
    content_type = filters.CharFilter(field_name="content_type__model")
    object_id = filters.NumberFilter(field_name="object_id")
    actor = filters.CharFilter(field_name="actor", lookup_expr="icontains")
    action_type = filters.CharFilter(field_name="action_type", lookup_expr="icontains")

    class Meta:
        model = ActivityLog
        fields = ["content_type", "object_id", "actor", "action_type"]

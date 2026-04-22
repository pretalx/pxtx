from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import DetailView, ListView

from pxtx.core.models import Issue, IssueReference


@login_required
def root_redirect(request):
    return redirect(reverse("core:issue-list"))


class IssueListView(LoginRequiredMixin, ListView):
    model = Issue
    template_name = "core/issue_list.html"
    context_object_name = "issues"

    def get_queryset(self):
        return Issue.objects.select_related("milestone")


class IssueDetailView(LoginRequiredMixin, DetailView):
    model = Issue
    template_name = "core/issue_detail.html"
    context_object_name = "issue"

    def get_object(self, queryset=None):
        qs = queryset if queryset is not None else self.get_queryset()
        return qs.select_related("milestone").get(number=self.kwargs["number"])

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        issue = self.object
        ctx["github_refs"] = list(issue.github_refs.all())
        ctx["comments"] = list(issue.comments.all())

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
        return ctx

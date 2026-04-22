from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.views.generic import DetailView, ListView

from pxtx.core.models import Milestone


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
        ctx["issues"] = list(self.object.issues.all())
        return ctx

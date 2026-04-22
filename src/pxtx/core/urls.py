from django.urls import path

from pxtx.core import views

app_name = "core"

urlpatterns = [
    path("", views.root_redirect, name="root"),
    path("issues/", views.IssueListView.as_view(), name="issue-list"),
    path("issues/<int:number>/", views.IssueDetailView.as_view(), name="issue-detail"),
    path("milestones/", views.MilestoneListView.as_view(), name="milestone-list"),
    path(
        "milestones/<slug:slug>/",
        views.MilestoneDetailView.as_view(),
        name="milestone-detail",
    ),
]

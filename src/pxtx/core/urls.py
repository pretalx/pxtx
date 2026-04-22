from django.urls import path

from pxtx.core import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("issues/", views.IssueListView.as_view(), name="issue-list"),
    path("issues/new/", views.IssueCreateView.as_view(), name="issue-new"),
    path(
        "issues/preview/", views.render_markdown_preview, name="issue-markdown-preview"
    ),
    path(
        "issues/blocked-reason/",
        views.blocked_reason_field,
        name="issue-blocked-reason",
    ),
    path("issues/<int:number>/", views.IssueDetailView.as_view(), name="issue-detail"),
    path(
        "issues/<int:number>/edit/", views.IssueUpdateView.as_view(), name="issue-edit"
    ),
    path(
        "issues/<int:number>/highlight/",
        views.IssueHighlightToggleView.as_view(),
        name="issue-highlight",
    ),
    path(
        "issues/<int:number>/description/",
        views.IssueDescriptionEditView.as_view(),
        name="issue-description",
    ),
    path(
        "issues/<int:number>/reorder/",
        views.IssueReorderView.as_view(),
        name="issue-reorder",
    ),
    path(
        "issues/<int:number>/comments/",
        views.CommentCreateView.as_view(),
        name="comment-create",
    ),
    path(
        "comments/<int:pk>/edit/", views.CommentEditView.as_view(), name="comment-edit"
    ),
    path("milestones/", views.MilestoneListView.as_view(), name="milestone-list"),
    path(
        "milestones/<slug:slug>/",
        views.MilestoneDetailView.as_view(),
        name="milestone-detail",
    ),
    path(
        "milestones/<slug:slug>/move/",
        views.MilestoneKanbanMoveView.as_view(),
        name="milestone-kanban-move",
    ),
    path("activity/", views.ActivityView.as_view(), name="activity"),
]

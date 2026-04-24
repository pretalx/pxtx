from django.urls import path
from django.views.generic import RedirectView

from pxtx.core import views

app_name = "core"

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="core:issue-list", permanent=False)),
    path("issues/", views.IssueListView.as_view(), name="issue-list"),
    path("issues/new/", views.IssueCreateView.as_view(), name="issue-new"),
    path(
        "issues/new/modal/",
        views.IssueModalCreateView.as_view(),
        name="issue-modal-new",
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
        "issues/<int:number>/modal-edit/",
        views.IssueModalEditView.as_view(),
        name="issue-modal-edit",
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
        "issues/<int:number>/cell/<str:field>/",
        views.IssueInlineCellView.as_view(),
        name="issue-cell",
    ),
    path(
        "issues/<int:number>/links/", views.IssueLinksView.as_view(), name="issue-links"
    ),
    path(
        "issues/<int:number>/links/<int:index>/delete/",
        views.IssueLinkDeleteView.as_view(),
        name="issue-link-delete",
    ),
    path(
        "issues/<int:number>/parties/",
        views.IssuePartiesView.as_view(),
        name="issue-parties",
    ),
    path(
        "issues/<int:number>/parties/<int:index>/delete/",
        views.IssuePartyDeleteView.as_view(),
        name="issue-party-delete",
    ),
    path(
        "issues/<int:number>/github-refs/",
        views.IssueGithubRefsView.as_view(),
        name="issue-github-refs",
    ),
    path(
        "issues/<int:number>/github-refs/<int:pk>/delete/",
        views.IssueGithubRefDeleteView.as_view(),
        name="issue-github-ref-delete",
    ),
    path(
        "issues/<int:number>/related/",
        views.IssueRelatedView.as_view(),
        name="issue-related",
    ),
    path(
        "issues/<int:number>/related/<int:pk>/delete/",
        views.IssueRelatedDeleteView.as_view(),
        name="issue-related-delete",
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
    path("milestones/new/", views.MilestoneCreateView.as_view(), name="milestone-new"),
    path(
        "milestones/<slug:slug>/",
        views.MilestoneDetailView.as_view(),
        name="milestone-detail",
    ),
    path(
        "milestones/<slug:slug>/edit/",
        views.MilestoneUpdateView.as_view(),
        name="milestone-edit",
    ),
    path(
        "milestones/<slug:slug>/release/",
        views.MilestoneReleaseToggleView.as_view(),
        name="milestone-release",
    ),
    path(
        "milestones/<slug:slug>/move/",
        views.MilestoneKanbanMoveView.as_view(),
        name="milestone-kanban-move",
    ),
    path("activity/", views.ActivityView.as_view(), name="activity"),
    path("deploy/", views.trigger_deploy, name="deploy"),
]

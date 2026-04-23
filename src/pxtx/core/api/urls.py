from django.urls import path
from rest_framework.routers import DefaultRouter

from pxtx.core.api import views

app_name = "api"

router = DefaultRouter()
router.register("issues", views.IssueViewSet, basename="issue")
router.register("milestones", views.MilestoneViewSet, basename="milestone")

urlpatterns = [
    path(
        "issues/<int:number>/comments/",
        views.IssueCommentsView.as_view(),
        name="issue-comments",
    ),
    path("comments/<int:pk>/", views.CommentEditView.as_view(), name="comment-edit"),
    path(
        "issues/<int:number>/github-refs/",
        views.IssueGithubRefsView.as_view(),
        name="issue-github-refs",
    ),
    path(
        "issues/<int:number>/github-refs/<int:pk>/",
        views.IssueGithubRefDeleteView.as_view(),
        name="issue-github-ref-detail",
    ),
    path(
        "issues/<int:number>/references/",
        views.IssueReferencesView.as_view(),
        name="issue-references",
    ),
    path(
        "issues/<int:number>/references/<int:pk>/",
        views.IssueReferenceDeleteView.as_view(),
        name="issue-reference-detail",
    ),
    path("activity/", views.ActivityLogView.as_view(), name="activity"),
    *router.urls,
]

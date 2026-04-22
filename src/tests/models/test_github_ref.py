import pytest
from django.db import IntegrityError, transaction

from pxtx.core.models import GithubRef, GithubRefKind
from tests.factories import (
    GithubCommitRefFactory,
    GithubIssueRefFactory,
    GithubPrRefFactory,
    IssueFactory,
)

pytestmark = pytest.mark.unit


@pytest.mark.django_db
def test_issue_ref_url_points_to_issues_page():
    ref = GithubIssueRefFactory(repo="pretalx/pretalx", number=1234)

    assert ref.url == "https://github.com/pretalx/pretalx/issues/1234"


@pytest.mark.django_db
def test_pr_ref_url_points_to_pull_page():
    ref = GithubPrRefFactory(repo="pretalx/pretalx", number=77)

    assert ref.url == "https://github.com/pretalx/pretalx/pull/77"


@pytest.mark.django_db
def test_commit_ref_url_uses_full_sha():
    ref = GithubCommitRefFactory(repo="pretalx/pretalx", sha="a" * 40)

    assert ref.url == f"https://github.com/pretalx/pretalx/commit/{'a' * 40}"


@pytest.mark.django_db
def test_issue_ref_display_uses_hash_sigil():
    ref = GithubIssueRefFactory(repo="pretalx/pretalx", number=1234)

    assert ref.display == "pretalx/pretalx#1234"


@pytest.mark.django_db
def test_pr_ref_display_uses_bang_sigil():
    ref = GithubPrRefFactory(repo="pretalx/pretalx", number=77)

    assert ref.display == "pretalx/pretalx!77"


@pytest.mark.django_db
def test_commit_ref_display_uses_short_sha():
    ref = GithubCommitRefFactory(
        repo="pretalx/pretalx", sha="abcdef0123456789" + "0" * 24
    )

    assert ref.display == "pretalx/pretalx@abcdef0"


@pytest.mark.django_db
def test_issue_ref_requires_number():
    issue = IssueFactory()

    with pytest.raises(IntegrityError), transaction.atomic():
        GithubRef.objects.create(
            issue=issue, kind=GithubRefKind.ISSUE, repo="pretalx/pretalx"
        )


@pytest.mark.django_db
def test_commit_ref_requires_sha():
    issue = IssueFactory()

    with pytest.raises(IntegrityError), transaction.atomic():
        GithubRef.objects.create(
            issue=issue, kind=GithubRefKind.COMMIT, repo="pretalx/pretalx", sha=""
        )


@pytest.mark.django_db
def test_github_ref_cascades_on_issue_delete():
    issue = IssueFactory()
    GithubIssueRefFactory(issue=issue)

    issue.delete()

    assert GithubRef.objects.count() == 0

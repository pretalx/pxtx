"""htmx-driven add/remove for the issue detail sidebar sections: external
links, interested parties, GitHub references, and linked issues."""

import pytest

from pxtx.core.models import ActivityLog, GithubRef, GithubRefKind, IssueReference
from tests.factories import (
    GithubCommitRefFactory,
    GithubIssueRefFactory,
    IssueFactory,
    IssueReferenceFactory,
)

pytestmark = pytest.mark.integration


# ---- detail page renders empty sections ------------------------------------


@pytest.mark.django_db
def test_issue_detail_always_renders_all_four_sidebar_sections(auth_client):
    issue = IssueFactory()

    response = auth_client.get(f"/issues/{issue.number}/")

    body = response.content.decode()
    assert 'id="issue-links"' in body
    assert 'id="issue-parties"' in body
    assert 'id="issue-github-refs"' in body
    assert 'id="issue-related"' in body
    # Empty-state placeholders appear so the user knows the section exists.
    assert "No links." in body
    assert "No interested parties." in body
    assert "No GitHub references." in body
    assert "No linked issues." in body


@pytest.mark.django_db
def test_issue_detail_lists_existing_links_parties_and_refs(auth_client):
    issue = IssueFactory(
        links=[{"label": "wiki", "url": "https://example.com/w"}],
        interested_parties=[
            {"label": "Alice", "url": "https://x/a", "note": "reporter"}
        ],
    )
    GithubIssueRefFactory(issue=issue, number=42, repo="pretalx/pretalx")
    other = IssueFactory(title="another")
    IssueReferenceFactory(from_issue=issue, to_issue=other)

    response = auth_client.get(f"/issues/{issue.number}/")

    body = response.content.decode()
    assert "wiki" in body
    assert "https://example.com/w" in body
    assert "Alice" in body
    assert "reporter" in body
    assert "pretalx/pretalx#42" in body
    assert other.slug in body


# ---- links: GET (toggle add form) ------------------------------------------


@pytest.mark.django_db
def test_links_get_default_shows_add_button_not_form(auth_client):
    issue = IssueFactory()

    response = auth_client.get(f"/issues/{issue.number}/links/")

    body = response.content.decode()
    assert "+ Add link" in body
    assert 'name="label"' not in body


@pytest.mark.django_db
def test_links_get_with_form_param_shows_inline_form(auth_client):
    issue = IssueFactory()

    response = auth_client.get(f"/issues/{issue.number}/links/?form=1")

    body = response.content.decode()
    assert 'name="label"' in body
    assert 'name="url"' in body
    assert "Add link" in body


# ---- links: POST add -------------------------------------------------------


@pytest.mark.django_db
def test_links_post_appends_to_links_and_logs(auth_client):
    issue = IssueFactory(links=[{"label": "first", "url": "https://a"}])
    before = ActivityLog.objects.filter(object_id=issue.pk).count()

    response = auth_client.post(
        f"/issues/{issue.number}/links/",
        data={"label": "wiki", "url": "https://example.com/w"},
    )

    issue.refresh_from_db()
    assert issue.links == [
        {"label": "first", "url": "https://a"},
        {"label": "wiki", "url": "https://example.com/w"},
    ]
    assert response.status_code == 200
    assert ActivityLog.objects.filter(object_id=issue.pk).count() == before + 1
    body = response.content.decode()
    assert "wiki" in body
    # Form is collapsed on success.
    assert 'name="label"' not in body


@pytest.mark.django_db
@pytest.mark.parametrize(
    "data",
    (
        {"label": "", "url": "https://x"},
        {"label": "x", "url": ""},
        {"label": "  ", "url": "  "},
    ),
)
def test_links_post_missing_fields_re_renders_form_with_error(auth_client, data):
    issue = IssueFactory()

    response = auth_client.post(f"/issues/{issue.number}/links/", data=data)

    issue.refresh_from_db()
    assert issue.links == []
    assert response.status_code == 200
    body = response.content.decode()
    assert "Both label and URL are required." in body
    # Draft values are preserved in the re-rendered form.
    if data["label"].strip():
        assert f'value="{data["label"]}"' in body


# ---- links: POST delete ----------------------------------------------------


@pytest.mark.django_db
def test_links_delete_by_index_removes_the_right_entry(auth_client):
    issue = IssueFactory(
        links=[
            {"label": "a", "url": "https://a"},
            {"label": "b", "url": "https://b"},
            {"label": "c", "url": "https://c"},
        ]
    )

    response = auth_client.post(f"/issues/{issue.number}/links/1/delete/")

    issue.refresh_from_db()
    assert issue.links == [
        {"label": "a", "url": "https://a"},
        {"label": "c", "url": "https://c"},
    ]
    assert response.status_code == 200
    assert "b" not in [link["label"] for link in issue.links]


@pytest.mark.django_db
def test_links_delete_out_of_range_index_is_a_noop(auth_client):
    issue = IssueFactory(links=[{"label": "a", "url": "https://a"}])

    response = auth_client.post(f"/issues/{issue.number}/links/9/delete/")

    issue.refresh_from_db()
    assert issue.links == [{"label": "a", "url": "https://a"}]
    assert response.status_code == 200


# ---- parties --------------------------------------------------------------


@pytest.mark.django_db
def test_parties_get_default_shows_add_button(auth_client):
    issue = IssueFactory()

    response = auth_client.get(f"/issues/{issue.number}/parties/")

    body = response.content.decode()
    assert "+ Add party" in body
    assert 'name="label"' not in body


@pytest.mark.django_db
def test_parties_get_with_form_param_shows_form(auth_client):
    issue = IssueFactory()

    response = auth_client.get(f"/issues/{issue.number}/parties/?form=1")

    body = response.content.decode()
    assert 'name="label"' in body
    assert 'name="url"' in body
    assert 'name="note"' in body


@pytest.mark.django_db
def test_parties_post_appends_with_optional_fields_only_when_present(auth_client):
    issue = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/parties/",
        data={"label": "Alice", "url": "", "note": "reporter"},
    )

    issue.refresh_from_db()
    assert issue.interested_parties == [{"label": "Alice", "note": "reporter"}]
    assert response.status_code == 200


@pytest.mark.django_db
def test_parties_post_with_url_keeps_url(auth_client):
    issue = IssueFactory()

    auth_client.post(
        f"/issues/{issue.number}/parties/",
        data={"label": "Bob", "url": "https://x/b", "note": ""},
    )

    issue.refresh_from_db()
    assert issue.interested_parties == [{"label": "Bob", "url": "https://x/b"}]


@pytest.mark.django_db
def test_parties_post_label_required(auth_client):
    issue = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/parties/",
        data={"label": "  ", "url": "https://x", "note": "n"},
    )

    issue.refresh_from_db()
    assert issue.interested_parties == []
    assert response.status_code == 200
    body = response.content.decode()
    assert "Label is required." in body
    assert 'value="https://x"' in body


@pytest.mark.django_db
def test_party_delete_by_index_removes_entry(auth_client):
    issue = IssueFactory(
        interested_parties=[{"label": "a"}, {"label": "b"}, {"label": "c"}]
    )

    response = auth_client.post(f"/issues/{issue.number}/parties/0/delete/")

    issue.refresh_from_db()
    assert issue.interested_parties == [{"label": "b"}, {"label": "c"}]
    assert response.status_code == 200


@pytest.mark.django_db
def test_party_delete_out_of_range_is_a_noop(auth_client):
    issue = IssueFactory(interested_parties=[{"label": "a"}])

    response = auth_client.post(f"/issues/{issue.number}/parties/5/delete/")

    issue.refresh_from_db()
    assert issue.interested_parties == [{"label": "a"}]
    assert response.status_code == 200


# ---- github refs ----------------------------------------------------------


@pytest.mark.django_db
def test_github_refs_get_with_form_param_shows_inputs_for_kind_and_repo(auth_client):
    issue = IssueFactory()

    response = auth_client.get(f"/issues/{issue.number}/github-refs/?form=1")

    body = response.content.decode()
    assert 'name="kind"' in body
    assert 'name="repo"' in body
    assert 'name="number"' in body
    assert 'name="sha"' in body
    # Repo defaults to the project's primary upstream so the common case
    # (linking a pretalx issue) needs no typing.
    assert "pretalx/pretalx" in body


@pytest.mark.django_db
def test_github_refs_post_creates_issue_ref(auth_client):
    issue = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/github-refs/",
        data={"kind": "issue", "repo": "pretalx/pretalx", "number": "777", "sha": ""},
    )

    assert response.status_code == 200
    refs = list(GithubRef.objects.filter(issue=issue))
    assert len(refs) == 1
    assert refs[0].kind == GithubRefKind.ISSUE
    assert refs[0].repo == "pretalx/pretalx"
    assert refs[0].number == 777


@pytest.mark.django_db
def test_github_refs_post_creates_commit_ref(auth_client):
    issue = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/github-refs/",
        data={
            "kind": "commit",
            "repo": "pretalx/pretalx",
            "number": "",
            "sha": "a" * 40,
        },
    )

    assert response.status_code == 200
    ref = GithubRef.objects.get(issue=issue)
    assert ref.kind == GithubRefKind.COMMIT
    assert ref.sha == "a" * 40


@pytest.mark.django_db
def test_github_refs_post_blank_repo_falls_back_to_default(auth_client):
    issue = IssueFactory()

    auth_client.post(
        f"/issues/{issue.number}/github-refs/",
        data={"kind": "pr", "repo": "", "number": "42", "sha": ""},
    )

    ref = GithubRef.objects.get(issue=issue)
    assert ref.repo == "pretalx/pretalx"


@pytest.mark.django_db
def test_github_refs_post_invalid_kind_re_renders_form_with_error(auth_client):
    issue = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/github-refs/",
        data={"kind": "nope", "repo": "x/y", "number": "1", "sha": ""},
    )

    assert GithubRef.objects.filter(issue=issue).count() == 0
    body = response.content.decode()
    assert "Pick a kind." in body


@pytest.mark.django_db
def test_github_refs_post_commit_without_sha_returns_error(auth_client):
    issue = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/github-refs/",
        data={"kind": "commit", "repo": "x/y", "number": "", "sha": ""},
    )

    assert GithubRef.objects.filter(issue=issue).count() == 0
    body = response.content.decode()
    assert "Commit SHA is required." in body


@pytest.mark.django_db
def test_github_refs_post_issue_with_non_integer_number_returns_error(auth_client):
    issue = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/github-refs/",
        data={"kind": "issue", "repo": "x/y", "number": "twelve", "sha": ""},
    )

    assert GithubRef.objects.filter(issue=issue).count() == 0
    body = response.content.decode()
    assert "Issue/PR number must be an integer." in body


@pytest.mark.django_db
def test_github_refs_post_duplicate_issue_ref_is_idempotent(auth_client):
    """Same kind/repo/number on the same issue should not produce a second
    GithubRef row — agents can re-add a link without growing the list."""
    issue = IssueFactory()
    GithubIssueRefFactory(issue=issue, repo="pretalx/pretalx", number=99)

    auth_client.post(
        f"/issues/{issue.number}/github-refs/",
        data={"kind": "issue", "repo": "pretalx/pretalx", "number": "99", "sha": ""},
    )

    assert GithubRef.objects.filter(issue=issue).count() == 1


@pytest.mark.django_db
def test_github_refs_post_duplicate_commit_ref_is_idempotent(auth_client):
    issue = IssueFactory()
    GithubCommitRefFactory(issue=issue, repo="pretalx/pretalx", sha="b" * 40)

    auth_client.post(
        f"/issues/{issue.number}/github-refs/",
        data={
            "kind": "commit",
            "repo": "pretalx/pretalx",
            "number": "",
            "sha": "b" * 40,
        },
    )

    assert GithubRef.objects.filter(issue=issue).count() == 1


@pytest.mark.django_db
def test_github_ref_delete_removes_ref(auth_client):
    issue = IssueFactory()
    ref = GithubIssueRefFactory(issue=issue)

    response = auth_client.post(f"/issues/{issue.number}/github-refs/{ref.pk}/delete/")

    assert response.status_code == 200
    assert GithubRef.objects.filter(pk=ref.pk).count() == 0


@pytest.mark.django_db
def test_github_ref_delete_scoped_to_issue(auth_client):
    """Posting against a different issue's URL must not delete a ref it
    doesn't own."""
    issue_a = IssueFactory()
    issue_b = IssueFactory()
    ref = GithubIssueRefFactory(issue=issue_a)

    auth_client.post(f"/issues/{issue_b.number}/github-refs/{ref.pk}/delete/")

    assert GithubRef.objects.filter(pk=ref.pk).exists()


@pytest.mark.django_db
def test_github_ref_add_logs_activity(auth_client):
    issue = IssueFactory()

    auth_client.post(
        f"/issues/{issue.number}/github-refs/",
        data={"kind": "issue", "repo": "pretalx/pretalx", "number": "55", "sha": ""},
    )

    entry = ActivityLog.objects.get(
        object_id=issue.pk, action_type="pxtx.issue.github_ref.added"
    )
    assert entry.data["kind"] == "issue"
    assert entry.data["repo"] == "pretalx/pretalx"
    assert entry.data["number"] == 55


@pytest.mark.django_db
def test_github_ref_duplicate_add_does_not_log(auth_client):
    """Idempotent adds should not spam the activity feed."""
    issue = IssueFactory()
    GithubIssueRefFactory(issue=issue, repo="pretalx/pretalx", number=99)

    auth_client.post(
        f"/issues/{issue.number}/github-refs/",
        data={"kind": "issue", "repo": "pretalx/pretalx", "number": "99", "sha": ""},
    )

    assert not ActivityLog.objects.filter(
        object_id=issue.pk, action_type="pxtx.issue.github_ref.added"
    ).exists()


@pytest.mark.django_db
def test_github_ref_delete_logs_activity(auth_client):
    issue = IssueFactory()
    ref = GithubIssueRefFactory(issue=issue, repo="pretalx/pretalx", number=12)

    auth_client.post(f"/issues/{issue.number}/github-refs/{ref.pk}/delete/")

    entry = ActivityLog.objects.get(
        object_id=issue.pk, action_type="pxtx.issue.github_ref.removed"
    )
    assert entry.data["number"] == 12


# ---- related (linked issues) ----------------------------------------------


@pytest.mark.django_db
def test_related_get_with_form_shows_typeahead_datalist(auth_client):
    issue = IssueFactory()
    other = IssueFactory(title="typeahead target")

    response = auth_client.get(f"/issues/{issue.number}/related/?form=1")

    body = response.content.decode()
    assert 'list="issue-related-options"' in body
    assert "<datalist" in body
    assert f'value="PX-{other.number}"' in body
    assert "typeahead target" in body
    # The current issue is excluded from its own datalist.
    assert f'value="PX-{issue.number}"' not in body


@pytest.mark.django_db
def test_related_post_with_px_slug_creates_reference(auth_client):
    issue = IssueFactory()
    other = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/related/", data={"target": f"PX-{other.number}"}
    )

    assert response.status_code == 200
    ref = IssueReference.objects.get()
    assert ref.from_issue == issue
    assert ref.to_issue == other


@pytest.mark.django_db
@pytest.mark.parametrize("value", ("PX-{n}", "px-{n}", "{n}", "#{n}"))
def test_related_post_accepts_various_target_formats(auth_client, value):
    issue = IssueFactory()
    other = IssueFactory()

    auth_client.post(
        f"/issues/{issue.number}/related/",
        data={"target": value.format(n=other.number)},
    )

    assert IssueReference.objects.filter(from_issue=issue, to_issue=other).exists()


@pytest.mark.django_db
def test_related_post_blank_target_returns_error(auth_client):
    issue = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/related/", data={"target": " "}
    )

    assert IssueReference.objects.count() == 0
    body = response.content.decode()
    assert "Enter an issue number" in body


@pytest.mark.django_db
def test_related_post_unparseable_target_returns_error(auth_client):
    issue = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/related/", data={"target": "garbage"}
    )

    assert IssueReference.objects.count() == 0
    body = response.content.decode()
    assert "Enter an issue number" in body


@pytest.mark.django_db
def test_related_post_zero_or_negative_number_returns_error(auth_client):
    issue = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/related/", data={"target": "PX-0"}
    )

    assert IssueReference.objects.count() == 0
    body = response.content.decode()
    assert "Enter an issue number" in body


@pytest.mark.django_db
def test_related_post_self_reference_returns_error(auth_client):
    issue = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/related/", data={"target": f"PX-{issue.number}"}
    )

    assert IssueReference.objects.count() == 0
    body = response.content.decode()
    assert "cannot reference itself" in body


@pytest.mark.django_db
def test_related_post_unknown_issue_returns_error(auth_client):
    issue = IssueFactory()

    response = auth_client.post(
        f"/issues/{issue.number}/related/", data={"target": "PX-99999"}
    )

    assert IssueReference.objects.count() == 0
    body = response.content.decode()
    assert "No issue PX-99999" in body


@pytest.mark.django_db
def test_related_post_duplicate_reference_is_idempotent(auth_client):
    issue = IssueFactory()
    other = IssueFactory()
    IssueReferenceFactory(from_issue=issue, to_issue=other)

    auth_client.post(
        f"/issues/{issue.number}/related/", data={"target": f"PX-{other.number}"}
    )

    assert IssueReference.objects.count() == 1


@pytest.mark.django_db
def test_related_post_skips_when_reverse_already_exists(auth_client):
    """References are symmetric — B→A already covers A→B."""
    issue = IssueFactory()
    other = IssueFactory()
    IssueReferenceFactory(from_issue=other, to_issue=issue)

    auth_client.post(
        f"/issues/{issue.number}/related/", data={"target": f"PX-{other.number}"}
    )

    assert IssueReference.objects.count() == 1


@pytest.mark.django_db
def test_related_delete_removes_reference(auth_client):
    issue = IssueFactory()
    other = IssueFactory()
    ref = IssueReferenceFactory(from_issue=issue, to_issue=other)

    response = auth_client.post(f"/issues/{issue.number}/related/{ref.pk}/delete/")

    assert response.status_code == 200
    assert IssueReference.objects.count() == 0


@pytest.mark.django_db
def test_related_delete_works_from_target_side(auth_client):
    """Either endpoint of the edge can delete it — the row has direction
    but the link is logically symmetric."""
    issue = IssueFactory()
    other = IssueFactory()
    ref = IssueReferenceFactory(from_issue=other, to_issue=issue)

    auth_client.post(f"/issues/{issue.number}/related/{ref.pk}/delete/")

    assert IssueReference.objects.count() == 0


@pytest.mark.django_db
def test_related_delete_does_not_remove_unrelated_reference(auth_client):
    """If the reference does not touch this issue, it must not be deleted
    via this issue's URL."""
    a = IssueFactory()
    b = IssueFactory()
    c = IssueFactory()
    ref = IssueReferenceFactory(from_issue=b, to_issue=c)

    auth_client.post(f"/issues/{a.number}/related/{ref.pk}/delete/")

    assert IssueReference.objects.filter(pk=ref.pk).exists()


@pytest.mark.django_db
def test_related_delete_missing_pk_is_a_noop(auth_client):
    issue = IssueFactory()

    response = auth_client.post(f"/issues/{issue.number}/related/9999/delete/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_related_add_logs_activity(auth_client):
    issue = IssueFactory()
    other = IssueFactory()

    auth_client.post(
        f"/issues/{issue.number}/related/", data={"target": f"PX-{other.number}"}
    )

    entry = ActivityLog.objects.get(
        object_id=issue.pk, action_type="pxtx.issue.related.added"
    )
    assert entry.data["other_number"] == other.number


@pytest.mark.django_db
def test_related_duplicate_add_does_not_log(auth_client):
    issue = IssueFactory()
    other = IssueFactory()
    IssueReferenceFactory(from_issue=issue, to_issue=other)

    auth_client.post(
        f"/issues/{issue.number}/related/", data={"target": f"PX-{other.number}"}
    )

    assert not ActivityLog.objects.filter(
        object_id=issue.pk, action_type="pxtx.issue.related.added"
    ).exists()


@pytest.mark.django_db
def test_related_delete_logs_activity(auth_client):
    issue = IssueFactory()
    other = IssueFactory()
    ref = IssueReferenceFactory(from_issue=issue, to_issue=other)

    auth_client.post(f"/issues/{issue.number}/related/{ref.pk}/delete/")

    entry = ActivityLog.objects.get(
        object_id=issue.pk, action_type="pxtx.issue.related.removed"
    )
    assert entry.data["other_number"] == other.number


# ---- auth -----------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    (
        "/issues/{n}/links/",
        "/issues/{n}/parties/",
        "/issues/{n}/github-refs/",
        "/issues/{n}/related/",
    ),
)
def test_sidebar_section_endpoints_require_login(client, url):
    issue = IssueFactory()

    response = client.get(url.format(n=issue.number))

    assert response.status_code == 302
    assert response.url.startswith("/login/")

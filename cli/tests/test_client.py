from __future__ import annotations

import pytest

from pxtx.client import ApiError, Client

URL = "https://tracker.example.test"


@pytest.fixture
def client_plain():
    return Client(URL + "/", "pxtx_test")


def test_url_strips_trailing_slash(client_plain):
    assert client_plain.url == URL


def test_get_issue(mocked_responses, client_plain):
    mocked_responses.get(
        f"{URL}/api/v1/issues/47/", json={"slug": "PX-47", "number": 47, "title": "hi"}
    )

    result = client_plain.get_issue(47)

    assert result == {"slug": "PX-47", "number": 47, "title": "hi"}
    assert (
        mocked_responses.calls[0].request.headers["Authorization"] == "Token pxtx_test"
    )


def test_create_issue_posts_json(mocked_responses, client_plain):
    mocked_responses.post(
        f"{URL}/api/v1/issues/",
        json={"slug": "PX-1", "number": 1, "title": "x"},
        status=201,
    )

    result = client_plain.create_issue({"title": "x"})

    assert result == {"slug": "PX-1", "number": 1, "title": "x"}


def test_update_issue(mocked_responses, client_plain):
    mocked_responses.patch(
        f"{URL}/api/v1/issues/5/", json={"slug": "PX-5", "title": "new"}
    )

    result = client_plain.update_issue(5, {"title": "new"})

    assert result["title"] == "new"


def test_transition_issue(mocked_responses, client_plain):
    mocked_responses.post(
        f"{URL}/api/v1/issues/5/completed/",
        json={"slug": "PX-5", "status": "completed"},
    )

    result = client_plain.transition_issue(5, "completed")

    assert result["status"] == "completed"


def test_transition_issue_with_payload(mocked_responses, client_plain):
    mocked_responses.post(
        f"{URL}/api/v1/issues/5/blocked/",
        json={"slug": "PX-5", "status": "blocked", "blocked_reason": "x"},
    )

    result = client_plain.transition_issue(5, "blocked", {"blocked_reason": "x"})

    assert result["blocked_reason"] == "x"


def test_add_comment(mocked_responses, client_plain):
    mocked_responses.post(
        f"{URL}/api/v1/issues/5/comments/",
        json={"id": 1, "author": "claude/x", "body": "hello"},
        status=201,
    )

    result = client_plain.add_comment(5, "hello")

    assert result["id"] == 1


def test_list_comments_paginates(mocked_responses, client_plain):
    mocked_responses.get(
        f"{URL}/api/v1/issues/5/comments/",
        json={"results": [{"id": 1}], "next": f"{URL}/api/v1/issues/5/comments/?p=2"},
    )
    mocked_responses.get(
        f"{URL}/api/v1/issues/5/comments/?p=2",
        json={"results": [{"id": 2}], "next": None},
    )

    result = client_plain.list_comments(5)

    assert [c["id"] for c in result] == [1, 2]


def test_list_issues_drops_none_filters(mocked_responses, client_plain):
    mocked_responses.get(
        f"{URL}/api/v1/issues/", json={"results": [{"slug": "PX-1"}], "next": None}
    )

    result = list(client_plain.list_issues(status="open", priority=None))

    assert result == [{"slug": "PX-1"}]
    call = mocked_responses.calls[0].request
    assert "status=open" in call.url
    assert "priority" not in call.url


def test_list_milestones(mocked_responses, client_plain):
    mocked_responses.get(
        f"{URL}/api/v1/milestones/", json={"results": [{"slug": "r1"}], "next": None}
    )

    assert [m["slug"] for m in client_plain.list_milestones()] == ["r1"]


def test_activity_log(mocked_responses, client_plain):
    mocked_responses.get(
        f"{URL}/api/v1/activity/",
        json={"results": [{"id": 1, "action_type": "pxtx.issue.create"}], "next": None},
    )

    result = list(client_plain.activity_log(issue=47))

    assert result[0]["action_type"] == "pxtx.issue.create"
    assert "issue=47" in mocked_responses.calls[0].request.url


def test_error_response_with_json_body(mocked_responses, client_plain):
    mocked_responses.post(
        f"{URL}/api/v1/issues/", json={"title": ["required"]}, status=400
    )

    with pytest.raises(ApiError) as excinfo:
        client_plain.create_issue({})

    assert excinfo.value.status == 400
    assert excinfo.value.body == {"title": ["required"]}


def test_error_response_with_text_body(mocked_responses, client_plain):
    mocked_responses.get(
        f"{URL}/api/v1/issues/1/",
        body="server oops",
        status=500,
        content_type="text/plain",
    )

    with pytest.raises(ApiError) as excinfo:
        client_plain.get_issue(1)

    assert excinfo.value.status == 500
    assert excinfo.value.body == "server oops"


def test_paginate_error_raises(mocked_responses, client_plain):
    mocked_responses.get(
        f"{URL}/api/v1/issues/", json={"detail": "bad filter"}, status=400
    )

    with pytest.raises(ApiError):
        list(client_plain.list_issues(status="open"))


def test_request_returns_none_on_204(mocked_responses, client_plain):
    mocked_responses.delete(f"{URL}/api/v1/issues/1/github-refs/5/", status=204)

    # Use _request directly to exercise the 204 branch.
    result = client_plain._request("DELETE", "/issues/1/github-refs/5/")

    assert result is None


def test_client_uses_provided_session():
    # Passing a session lets tests share the responses mock without the client
    # spinning up a fresh one — exercises the ``session=`` branch.
    import requests

    session = requests.Session()
    client = Client(URL, "tok", session=session)
    assert client.session is session

from __future__ import annotations

import argparse
import io
import json
from datetime import UTC, datetime

import pytest

from pxtx import cli

URL = "https://tracker.example.test"


def test_parse_issue_id_accepts_px_prefix():
    assert cli.parse_issue_id("PX-47") == 47


def test_parse_issue_id_accepts_lower_case():
    assert cli.parse_issue_id("px-47") == 47


def test_parse_issue_id_accepts_bare_number():
    assert cli.parse_issue_id("47") == 47


def test_parse_issue_id_rejects_garbage():
    with pytest.raises(argparse.ArgumentTypeError):
        cli.parse_issue_id("not-an-id")


def test_parse_priority_csv_valid():
    assert cli.parse_priority_csv("want, should") == ["want", "should"]


def test_parse_priority_csv_rejects_unknown():
    with pytest.raises(argparse.ArgumentTypeError, match="nope"):
        cli.parse_priority_csv("want,nope")


def test_parse_priority_csv_rejects_empty():
    with pytest.raises(argparse.ArgumentTypeError, match="empty"):
        cli.parse_priority_csv(" , ")


def test_issue_list_priority_unknown_errors_at_parse(cli_config, capsys):
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["issue", "list", "--priority", "fooo"])

    assert excinfo.value.code == 2
    assert "unknown priority" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("value", "unit_seconds"),
    (("30m", 30 * 60), ("2h", 2 * 3600), ("3d", 3 * 86400), ("1w", 7 * 86400)),
)
def test_parse_since_durations(value, unit_seconds):
    anchor = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)

    result = cli.parse_since(value, now=anchor)

    delta = anchor - datetime.fromisoformat(result)
    assert int(delta.total_seconds()) == unit_seconds


def test_parse_since_iso_passthrough():
    iso = "2026-04-22T10:00:00+00:00"

    assert cli.parse_since(iso) == iso


def test_parse_since_invalid_raises():
    with pytest.raises(cli.CliError):
        cli.parse_since("garbage")


def test_get_branch_returns_stripped(monkeypatch):
    monkeypatch.setattr(cli, "_run_git_branch", lambda: "feat/x")

    assert cli.get_branch() == "feat/x"


def test_run_git_branch_handles_success(monkeypatch):
    import subprocess

    def fake_run(*args, **kwargs):
        class R:
            stdout = "main\n"

        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert cli._run_git_branch() == "main"


def test_run_git_branch_handles_empty(monkeypatch):
    import subprocess

    def fake_run(*args, **kwargs):
        class R:
            stdout = "\n"

        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert cli._run_git_branch() is None


def test_run_git_branch_handles_missing_git(monkeypatch):
    import subprocess

    def fake_run(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert cli._run_git_branch() is None


def test_run_git_branch_handles_non_repo(monkeypatch):
    import subprocess

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(128, "git")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert cli._run_git_branch() is None


def test_resolve_actor_explicit_wins(monkeypatch):
    monkeypatch.delenv("CLAUDECODE", raising=False)

    assert cli.resolve_actor("tobias") == "tobias"


def test_resolve_actor_outside_claude_code_is_empty(monkeypatch):
    monkeypatch.delenv("CLAUDECODE", raising=False)

    assert cli.resolve_actor(None) == ""


def test_resolve_actor_wrong_value_does_not_trigger_claude(monkeypatch):
    """Any value other than ``1`` is treated as 'not claude-code'."""
    monkeypatch.setenv("CLAUDECODE", "true")

    assert cli.resolve_actor(None) == ""


def test_resolve_actor_in_claude_code_uses_branch(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(cli, "_run_git_branch", lambda: "feat/x")

    assert cli.resolve_actor(None) == "claude-feat/x"


def test_resolve_actor_in_claude_code_without_branch_falls_back_to_claude(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(cli, "_run_git_branch", lambda: None)

    assert cli.resolve_actor(None) == "claude"


def test_print_json_writes_to_provided_stream():
    out = io.StringIO()

    cli.print_json({"a": 1}, out=out)

    assert out.getvalue() == '{\n  "a": 1\n}\n'


def test_print_json_defaults_to_stdout(capsys):
    cli.print_json({"x": 2})

    assert capsys.readouterr().out == '{\n  "x": 2\n}\n'


# ---------- main() integration ----------


def _run(argv, cli_config, mocked_responses=None):  # helper to invoke main()
    return cli.main(argv)


def test_main_config_error_returns_2(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("PXTX_CONFIG", str(tmp_path / "nope.toml"))

    code = cli.main(["issue", "list"])

    assert code == 2
    assert "error:" in capsys.readouterr().err


def test_main_api_error_returns_1(cli_config, mocked_responses, capsys):
    mocked_responses.get(f"{URL}/api/v1/issues/", json={"detail": "x"}, status=500)

    code = cli.main(["issue", "list"])

    assert code == 1
    assert "api error:" in capsys.readouterr().err


def test_issue_new_posts_payload(cli_config, mocked_responses, capsys):
    mocked_responses.post(
        f"{URL}/api/v1/issues/",
        json={"slug": "PX-1", "number": 1, "title": "hello"},
        status=201,
    )

    code = cli.main(
        [
            "issue",
            "new",
            "--title",
            "hello",
            "--priority",
            "want",
            "--effort",
            "2-6h",
            "--milestone",
            "r1",
            "--description",
            "body",
            "--assignee",
            "someone",
        ]
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "created PX-1" in out
body = json.loads(mocked_responses.calls[0].request.body)
    assert body == {
        "title": "hello",
        "priority": 1,
        "effort_minutes": 240,
        "milestone": "r1",
        "description": "body",
        "assignee": "someone",
    }


def test_issue_new_json_output(cli_config, mocked_responses, capsys):
    mocked_responses.post(
        f"{URL}/api/v1/issues/",
        json={"slug": "PX-1", "number": 1, "title": "x"},
        status=201,
    )

    code = cli.main(["--json", "issue", "new", "--title", "x"])

    assert code == 0
    out = capsys.readouterr().out
    assert '"slug": "PX-1"' in out


def test_issue_list_formats_rows(cli_config, mocked_responses, capsys):
    mocked_responses.get(
        f"{URL}/api/v1/issues/",
        json={
            "results": [
                {
                    "slug": "PX-1",
                    "status": "open",
                    "priority": 1,
                    "assignee": "me",
                    "title": "thing",
                }
            ],
            "next": None,
        },
    )

    code = cli.main(["issue", "list"])

    assert code == 0
    assert "PX-1" in capsys.readouterr().out


def test_issue_list_applies_filters(cli_config, mocked_responses, capsys):
    mocked_responses.get(f"{URL}/api/v1/issues/", json={"results": [], "next": None})

    code = cli.main(
        [
            "issue",
            "list",
            "--status",
            "open,wip",
            "--priority",
            "want,should",
            "--milestone",
            "r1",
            "--assignee",
            "claude/x",
            "--highlighted",
            "--search",
            "hay",
        ]
    )

    assert code == 0
    url = mocked_responses.calls[0].request.url
    assert "status=open%2Cwip" in url
    assert "priority=1%2C2" in url
    assert "milestone=r1" in url
    assert "assignee=claude%2Fx" in url
    assert "is_highlighted=true" in url
    assert "search=hay" in url


def test_issue_list_mine_uses_resolved_actor(cli_config, mocked_responses, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(cli, "_run_git_branch", lambda: "feat/x")
    mocked_responses.get(f"{URL}/api/v1/issues/", json={"results": [], "next": None})

    cli.main(["issue", "list", "--mine"])

    url = mocked_responses.calls[0].request.url
    assert "assignee=claude-feat%2Fx" in url


def test_issue_list_mine_without_actor_errors(cli_config, capsys):
    code = cli.main(["issue", "list", "--mine"])

    assert code == 2
    assert "--mine" in capsys.readouterr().err


def test_top_level_actor_flag_overrides_resolution(cli_config, mocked_responses):
    mocked_responses.get(f"{URL}/api/v1/issues/", json={"results": [], "next": None})

    cli.main(["--actor", "tobias", "issue", "list", "--mine"])

    request = mocked_responses.calls[0].request
    assert "assignee=tobias" in request.url
    assert request.headers.get("X-Pxtx-Actor") == "tobias"


def test_top_level_actor_flag_beats_claude_code_default(
    cli_config, mocked_responses, monkeypatch
):
    """``--actor`` wins over the auto-derived ``claude-<branch>`` inside a
    claude-code session — that's the precedence users rely on when handing
    an issue off to a human."""
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(cli, "_run_git_branch", lambda: "feat/x")
    mocked_responses.get(f"{URL}/api/v1/issues/", json={"results": [], "next": None})

    cli.main(["--actor", "tobias", "issue", "list", "--mine"])

    request = mocked_responses.calls[0].request
    assert "assignee=tobias" in request.url
    assert request.headers.get("X-Pxtx-Actor") == "tobias"


def test_issue_list_json_output(cli_config, mocked_responses, capsys):
    mocked_responses.get(
        f"{URL}/api/v1/issues/", json={"results": [{"slug": "PX-1"}], "next": None}
    )

    code = cli.main(["--json", "issue", "list"])

    assert code == 0
    assert '"slug": "PX-1"' in capsys.readouterr().out


def test_issue_show_prints_detail(cli_config, mocked_responses, capsys):
    mocked_responses.get(
        f"{URL}/api/v1/issues/47/",
        json={
            "slug": "PX-47",
            "title": "x",
            "status": "open",
            "priority": 3,
            "effort_minutes": None,
            "assignee": "",
            "milestone": None,
            "created_at": "2026-04-22T10:00:00+00:00",
            "updated_at": "2026-04-22T10:00:00+00:00",
        },
    )

    code = cli.main(["issue", "show", "PX-47"])

    assert code == 0
    assert "PX-47: x" in capsys.readouterr().out


def test_issue_show_with_comments(cli_config, mocked_responses, capsys):
    mocked_responses.get(
        f"{URL}/api/v1/issues/7/",
        json={
            "slug": "PX-7",
            "title": "x",
            "status": "open",
            "priority": 3,
            "effort_minutes": None,
            "assignee": "",
            "milestone": None,
            "created_at": "2026-04-22T10:00:00+00:00",
            "updated_at": "2026-04-22T10:00:00+00:00",
        },
    )
    mocked_responses.get(
        f"{URL}/api/v1/issues/7/comments/",
        json={
            "results": [
                {
                    "id": 1,
                    "author": "tobias",
                    "body": "hi",
                    "created_at": "2026-04-22T10:05:00+00:00",
                }
            ],
            "next": None,
        },
    )

    code = cli.main(["issue", "show", "7", "--comments"])

    assert code == 0
    out = capsys.readouterr().out
    assert "=== comments (1) ===" in out
    assert "tobias" in out


def test_issue_show_json_with_comments(cli_config, mocked_responses, capsys):
    mocked_responses.get(f"{URL}/api/v1/issues/7/", json={"slug": "PX-7", "title": "x"})
    mocked_responses.get(
        f"{URL}/api/v1/issues/7/comments/", json={"results": [{"id": 1}], "next": None}
    )

    cli.main(["--json", "issue", "show", "7", "--comments"])

    out = capsys.readouterr().out
    assert '"issue"' in out
    assert '"comments"' in out


def test_issue_show_json_without_comments(cli_config, mocked_responses, capsys):
    mocked_responses.get(f"{URL}/api/v1/issues/7/", json={"slug": "PX-7", "title": "x"})

    cli.main(["--json", "issue", "show", "7"])

    out = capsys.readouterr().out
    assert '"comments"' not in out


def test_issue_close_defaults_to_completed(cli_config, mocked_responses, capsys):
    mocked_responses.post(
        f"{URL}/api/v1/issues/5/completed/",
        json={"slug": "PX-5", "status": "completed"},
    )

    code = cli.main(["issue", "close", "PX-5"])

    assert code == 0
    assert "PX-5" in capsys.readouterr().out


def test_issue_close_wontfix(cli_config, mocked_responses, capsys):
    mocked_responses.post(
        f"{URL}/api/v1/issues/5/wontfix/", json={"slug": "PX-5", "status": "wontfix"}
    )

    code = cli.main(["issue", "close", "5", "--wontfix"])

    assert code == 0
    assert "wontfix" in capsys.readouterr().out


def test_issue_close_json(cli_config, mocked_responses, capsys):
    mocked_responses.post(
        f"{URL}/api/v1/issues/5/completed/",
        json={"slug": "PX-5", "status": "completed"},
    )

    cli.main(["--json", "issue", "close", "5"])

    assert '"status": "completed"' in capsys.readouterr().out


def test_take_sets_assignee_and_wips(cli_config, mocked_responses, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(cli, "_run_git_branch", lambda: "feat/x")
    mocked_responses.patch(
        f"{URL}/api/v1/issues/47/", json={"slug": "PX-47", "assignee": "claude-feat/x"}
    )
    mocked_responses.post(
        f"{URL}/api/v1/issues/47/wip/",
        json={"slug": "PX-47", "status": "wip", "assignee": "claude-feat/x"},
    )

    code = cli.main(["take", "47"])

    assert code == 0
patch_body = json.loads(mocked_responses.calls[0].request.body)
    assert patch_body == {"assignee": "claude-feat/x"}
    assert "PX-47 → wip" in capsys.readouterr().out


def test_take_without_actor_errors(cli_config, capsys):
    code = cli.main(["take", "47"])

    assert code == 2
    assert "actor" in capsys.readouterr().err


def test_take_json_output(cli_config, mocked_responses, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setattr(cli, "_run_git_branch", lambda: "main")
    mocked_responses.patch(
        f"{URL}/api/v1/issues/47/", json={"slug": "PX-47", "assignee": "claude-main"}
    )
    mocked_responses.post(
        f"{URL}/api/v1/issues/47/wip/",
        json={"slug": "PX-47", "status": "wip", "assignee": "claude-main"},
    )

    cli.main(["--json", "take", "47"])

    assert '"status": "wip"' in capsys.readouterr().out


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("42", ("pretalx/pretalx", 42)),
        ("owner/repo#7", ("owner/repo", 7)),
        ("owner/repo!7", ("owner/repo", 7)),
        ("https://github.com/owner/repo/pull/99", ("owner/repo", 99)),
        ("https://github.com/owner/repo/pull/99/files", ("owner/repo", 99)),
        ("HTTPS://GitHub.com/Owner/Repo/pull/3", ("Owner/Repo", 3)),
    ),
)
def test_parse_pr_ref_accepts_known_forms(value, expected):
    assert cli.parse_pr_ref(value, default_repo="pretalx/pretalx") == expected


def test_parse_pr_ref_bare_number_requires_default_repo():
    with pytest.raises(cli.CliError, match="default_repo"):
        cli.parse_pr_ref("42", default_repo="")


def test_parse_pr_ref_rejects_garbage():
    with pytest.raises(cli.CliError, match="not a PR reference"):
        cli.parse_pr_ref("not-a-ref", default_repo="pretalx/pretalx")


def test_pr_link_uses_default_repo(cli_config, mocked_responses, capsys):
    mocked_responses.post(
        f"{URL}/api/v1/issues/47/github-refs/",
        json={
            "id": 3,
            "kind": "pr",
            "repo": "pretalx/pretalx",
            "number": 9912,
            "display": "pretalx/pretalx!9912",
        },
        status=201,
    )

    code = cli.main(["pr", "47", "9912"])

    assert code == 0
body = json.loads(mocked_responses.calls[0].request.body)
    assert body == {"kind": "pr", "repo": "pretalx/pretalx", "number": 9912}
    assert "PX-47 ↔ pretalx/pretalx!9912" in capsys.readouterr().out


def test_pr_link_with_explicit_repo_and_url(cli_config, mocked_responses):
    mocked_responses.post(
        f"{URL}/api/v1/issues/47/github-refs/",
        json={
            "id": 4,
            "kind": "pr",
            "repo": "acme/widget",
            "number": 7,
            "display": "acme/widget!7",
        },
        status=201,
    )

    cli.main(["pr", "47", "https://github.com/acme/widget/pull/7"])

body = json.loads(mocked_responses.calls[0].request.body)
    assert body == {"kind": "pr", "repo": "acme/widget", "number": 7}


def test_pr_link_json_output(cli_config, mocked_responses, capsys):
    mocked_responses.post(
        f"{URL}/api/v1/issues/47/github-refs/",
        json={
            "id": 5,
            "kind": "pr",
            "repo": "pretalx/pretalx",
            "number": 1,
            "display": "pretalx/pretalx!1",
        },
        status=201,
    )

    cli.main(["--json", "pr", "47", "1"])

    assert '"display": "pretalx/pretalx!1"' in capsys.readouterr().out


def test_issue_comment_with_body(cli_config, mocked_responses, capsys):
    mocked_responses.post(
        f"{URL}/api/v1/issues/5/comments/", json={"id": 99, "body": "hello"}, status=201
    )

    code = cli.main(["issue", "comment", "5", "hello"])

    assert code == 0
    assert "added comment #99 to PX-5" in capsys.readouterr().out


def test_issue_comment_from_stdin(cli_config, mocked_responses, monkeypatch, capsys):
    mocked_responses.post(
        f"{URL}/api/v1/issues/5/comments/", json={"id": 99, "body": "hello"}, status=201
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("piped body"))

    code = cli.main(["issue", "comment", "5"])

    assert code == 0
body = json.loads(mocked_responses.calls[0].request.body)
    assert body == {"body": "piped body"}


def test_issue_comment_empty_body_errors(cli_config, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("   \n"))

    code = cli.main(["issue", "comment", "5"])

    assert code == 2
    assert "empty" in capsys.readouterr().err


def test_issue_comment_json(cli_config, mocked_responses, capsys):
    mocked_responses.post(
        f"{URL}/api/v1/issues/5/comments/", json={"id": 99, "body": "hi"}, status=201
    )

    cli.main(["--json", "issue", "comment", "5", "hi"])

    assert '"id": 99' in capsys.readouterr().out


def test_issue_comment_forced_stdin_flag(cli_config, mocked_responses, monkeypatch):
    mocked_responses.post(
        f"{URL}/api/v1/issues/5/comments/", json={"id": 1, "body": "piped"}, status=201
    )
    monkeypatch.setattr("sys.stdin", io.StringIO("piped"))

    code = cli.main(["issue", "comment", "5", "arg-body", "--stdin"])

    assert code == 0
body = json.loads(mocked_responses.calls[0].request.body)
    assert body == {"body": "piped"}


def test_milestone_list(cli_config, mocked_responses, capsys):
    mocked_responses.get(
        f"{URL}/api/v1/milestones/",
        json={
            "results": [{"slug": "r1", "name": "Release 1", "target_date": None}],
            "next": None,
        },
    )

    code = cli.main(["milestone", "list"])

    assert code == 0
    assert "Release 1" in capsys.readouterr().out


def test_milestone_list_json(cli_config, mocked_responses, capsys):
    mocked_responses.get(
        f"{URL}/api/v1/milestones/",
        json={"results": [{"slug": "r1", "name": "Release 1"}], "next": None},
    )

    cli.main(["--json", "milestone", "list"])

    assert '"slug": "r1"' in capsys.readouterr().out


def test_activity_log_with_issue_and_since(
    cli_config, mocked_responses, monkeypatch, capsys
):
    fixed_now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(cli, "datetime", _FrozenDatetime(fixed_now))
    mocked_responses.get(
        f"{URL}/api/v1/activity/",
        json={
            "results": [
                {
                    "timestamp": "2026-04-22T11:30:00+00:00",
                    "actor": "tester",
                    "action_type": "pxtx.issue.create",
                    "content_type": "issue",
                    "object_id": 5,
                }
            ],
            "next": None,
        },
    )

    code = cli.main(["activity", "log", "PX-5", "--since", "1h"])

    assert code == 0
    url = mocked_responses.calls[0].request.url
    assert "issue=5" in url
    assert "since=2026-04-22T11%3A00%3A00%2B00%3A00" in url


def test_activity_log_no_filters(cli_config, mocked_responses, capsys):
    mocked_responses.get(f"{URL}/api/v1/activity/", json={"results": [], "next": None})

    code = cli.main(["activity", "log"])

    assert code == 0
    url = mocked_responses.calls[0].request.url
    assert "issue=" not in url
    assert "since=" not in url


def test_activity_log_json(cli_config, mocked_responses, capsys):
    mocked_responses.get(
        f"{URL}/api/v1/activity/",
        json={"results": [{"id": 1, "action_type": "x"}], "next": None},
    )

    cli.main(["--json", "activity", "log"])

    assert '"action_type": "x"' in capsys.readouterr().out


class _FrozenDatetime:
    """Minimal drop-in that freezes ``datetime.now`` while preserving other attrs."""

    def __init__(self, now):
        self._now = now
        self._dt = datetime

    def __getattr__(self, name):
        return getattr(self._dt, name)

    def now(self, tz=None):
        if tz is None:
            return self._now.replace(tzinfo=None)
        return self._now.astimezone(tz)

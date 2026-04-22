from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta

from pxtx.client import ApiError, Client
from pxtx.config import ConfigError, load_config
from pxtx.display import (
    format_activity_row,
    format_issue_detail,
    format_issue_row,
    format_milestone_row,
)

PRIORITY_MAP = {"want": 1, "should": 2, "could": 3, "whatev": 4, "lol": 5}
EFFORT_MAP = {"<1h": 30, "1-2h": 90, "2-6h": 240, "1d": 480, ">1d": 960}

SINCE_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


class CliError(Exception):
    pass


def parse_issue_id(value):
    """Accept ``PX-47``, ``px-47``, or the bare number."""
    match = re.fullmatch(r"(?:PX-)?(\d+)", value.strip(), flags=re.IGNORECASE)
    if not match:
        raise argparse.ArgumentTypeError(f"not an issue id: {value}")
    return int(match.group(1))


def parse_priority_csv(value):
    """Validate a comma-separated list of priority labels against PRIORITY_MAP."""
    labels = [p.strip() for p in value.split(",") if p.strip()]
    if not labels:
        raise argparse.ArgumentTypeError("priority list is empty")
    known = list(PRIORITY_MAP)
    bad = [label for label in labels if label not in PRIORITY_MAP]
    if bad:
        raise argparse.ArgumentTypeError(
            f"unknown priority {bad[0]!r}; choose from: {', '.join(known)}"
        )
    return labels


def parse_since(value, *, now=None):
    """Accept ``1h``/``30m``/``2d``/``1w`` or an ISO timestamp. Return ISO string."""
    match = re.fullmatch(r"(\d+)([mhdwMHDW])", value)
    if match:
        amount, unit = int(match.group(1)), match.group(2).lower()
        kwargs = {SINCE_UNITS[unit]: amount}
        anchor = now or datetime.now(UTC)
        return (anchor - timedelta(**kwargs)).isoformat()
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise CliError(f"not a duration or ISO timestamp: {value}") from exc
    return value


def get_branch(runner=None):
    runner = runner or _run_git_branch
    return runner()


def _run_git_branch():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    branch = result.stdout.strip()
    return branch or None


def resolve_actor(explicit):
    """Pick the ``X-Pxtx-Actor`` value sent with every request.

    Inside a claude-code session (``CLAUDECODE=1``) we derive
    ``claude-<branch>`` automatically so activity log entries identify
    which agent did what — humans don't have to remember. Outside that
    context we stay silent and let the server fall back to the token name,
    so a human poking the CLI doesn't accidentally label their edits
    ``claude-*``. ``--actor`` overrides both paths.
    """
    if explicit:
        return explicit
    if os.environ.get("CLAUDECODE") != "1":
        return ""
    branch = get_branch()
    if branch:
        return f"claude-{branch}"
    return "claude"


def print_json(value, out=None):
    out = out or sys.stdout
    json.dump(value, out, indent=2, default=str)
    out.write("\n")


def cmd_issue_new(args, client, config):
    # Parse the github ref up front so a bad value fails before we create
    # the issue — otherwise we'd end up with an orphaned PX ticket and a
    # user-facing error that looks like the create failed.
    github_ref_payload = None
    if args.github_issue:
        repo, number = parse_issue_ref(
            args.github_issue, default_repo=config.default_repo
        )
        github_ref_payload = {"kind": "issue", "repo": repo, "number": number}
    payload = {"title": args.title}
    if args.priority:
        payload["priority"] = PRIORITY_MAP[args.priority]
    if args.effort:
        payload["effort_minutes"] = EFFORT_MAP[args.effort]
    if args.milestone:
        payload["milestone"] = args.milestone
    if args.description:
        payload["description"] = args.description
    if args.assignee:
        payload["assignee"] = args.assignee
    issue = client.create_issue(payload)
    ref = None
    if github_ref_payload:
        ref = client.add_github_ref(issue["number"], github_ref_payload)
    if args.json:
        print_json({"issue": issue, "github_ref": ref} if ref else issue)
    else:
        print(f"created {issue['slug']}: {issue['title']}")
        if ref:
            print(f"  ↔ {ref['display']}")


def cmd_issue_list(args, client, config):
    filters = {}
    if args.status:
        filters["status"] = args.status
    if args.priority:
        filters["priority"] = ",".join(str(PRIORITY_MAP[p]) for p in args.priority)
    if args.milestone:
        filters["milestone"] = args.milestone
    if args.mine:
        if not client.actor:
            raise CliError(
                "--mine needs an actor (pass --actor or run inside claude-code)"
            )
        filters["assignee"] = client.actor
    elif args.assignee:
        filters["assignee"] = args.assignee
    if args.highlighted:
        filters["is_highlighted"] = "true"
    if args.search:
        filters["search"] = args.search
    issues = list(client.list_issues(**filters))
    if args.json:
        print_json(issues)
        return
    for issue in issues:
        print(format_issue_row(issue))


def cmd_issue_show(args, client, config):
    issue = client.get_issue(args.number)
    comments = client.list_comments(args.number) if args.comments else None
    if args.json:
        payload = {"issue": issue}
        if comments is not None:
            payload["comments"] = comments
        print_json(payload)
        return
    print(format_issue_detail(issue, comments))


def cmd_issue_take(args, client, config):
    """Claim an issue: set assignee to the current actor and status to wip."""
    if not client.actor:
        raise CliError("take needs an actor (pass --actor or run inside claude-code)")
    client.update_issue(args.number, {"assignee": client.actor})
    issue = client.transition_issue(args.number, "wip")
    if args.json:
        print_json(issue)
    else:
        print(f"{issue['slug']} → {issue['status']} (assignee: {issue['assignee']})")


PR_URL_PATTERN = re.compile(
    r"https?://github\.com/([^/]+/[^/]+)/pull/(\d+)(?:[/?#].*)?$", flags=re.IGNORECASE
)
PR_SHORT_PATTERN = re.compile(r"([^/\s]+/[^/\s#!]+)[#!](\d+)$")

ISSUE_URL_PATTERN = re.compile(
    r"https?://github\.com/([^/]+/[^/]+)/issues/(\d+)(?:[/?#].*)?$", flags=re.IGNORECASE
)
ISSUE_SHORT_PATTERN = re.compile(r"([^/\s]+/[^/\s#]+)#(\d+)$")


def parse_pr_ref(value, *, default_repo):
    """Parse a PR reference into ``(repo, number)``.

    Accepted forms:
    - ``42`` (bare number, uses ``default_repo``)
    - ``owner/repo#42`` or ``owner/repo!42``
    - ``https://github.com/owner/repo/pull/42``
    """
    value = value.strip()
    match = PR_URL_PATTERN.match(value)
    if match:
        return match.group(1), int(match.group(2))
    match = PR_SHORT_PATTERN.match(value)
    if match:
        return match.group(1), int(match.group(2))
    if value.isdigit():
        if not default_repo:
            raise CliError("bare PR number needs 'default_repo' in config")
        return default_repo, int(value)
    raise CliError(f"not a PR reference: {value}")


def parse_issue_ref(value, *, default_repo):
    """Parse a GitHub issue reference into ``(repo, number)``.

    Accepted forms:
    - ``42`` (bare number, uses ``default_repo``)
    - ``owner/repo#42``
    - ``https://github.com/owner/repo/issues/42``
    """
    value = value.strip()
    match = ISSUE_URL_PATTERN.match(value)
    if match:
        return match.group(1), int(match.group(2))
    match = ISSUE_SHORT_PATTERN.match(value)
    if match:
        return match.group(1), int(match.group(2))
    if value.isdigit():
        if not default_repo:
            raise CliError("bare issue number needs 'default_repo' in config")
        return default_repo, int(value)
    raise CliError(f"not an issue reference: {value}")


def cmd_pr_link(args, client, config):
    repo, number = parse_pr_ref(args.ref, default_repo=config.default_repo)
    ref = client.add_github_ref(
        args.number, {"kind": "pr", "repo": repo, "number": number}
    )
    if args.json:
        print_json(ref)
    else:
        print(f"PX-{args.number} ↔ {ref['display']}")


def cmd_issue_ref_link(args, client, config):
    repo, number = parse_issue_ref(args.ref, default_repo=config.default_repo)
    ref = client.add_github_ref(
        args.number, {"kind": "issue", "repo": repo, "number": number}
    )
    if args.json:
        print_json(ref)
    else:
        print(f"PX-{args.number} ↔ {ref['display']}")


def cmd_add_interested(args, client, config):
    entry = {"label": args.label}
    if args.url:
        entry["url"] = args.url
    if args.note:
        entry["note"] = args.note
    result = client.add_interested_party(args.number, entry)
    if args.json:
        print_json(result["issue"])
        return
    verb = "added interested" if result["created"] else "already interested"
    print(f"PX-{args.number} {verb}: {args.label}")


def cmd_add_link(args, client, config):
    entry = {"label": args.label, "url": args.url}
    result = client.add_link(args.number, entry)
    if args.json:
        print_json(result["issue"])
        return
    verb = "added link" if result["created"] else "already linked"
    print(f"PX-{args.number} {verb}: {args.label} → {args.url}")


def cmd_issue_close(args, client, config):
    action = "wontfix" if args.wontfix else "completed"
    issue = client.transition_issue(args.number, action)
    if args.json:
        print_json(issue)
    else:
        print(f"{issue['slug']} → {issue['status']}")


def cmd_issue_comment(args, client, config):
    body = args.body
    if args.stdin or body is None:
        body = sys.stdin.read()
    if not body.strip():
        raise CliError("comment body is empty")
    comment = client.add_comment(args.number, body)
    if args.json:
        print_json(comment)
    else:
        print(f"added comment #{comment['id']} to PX-{args.number}")


def cmd_milestone_list(args, client, config):
    milestones = list(client.list_milestones())
    if args.json:
        print_json(milestones)
        return
    for milestone in milestones:
        print(format_milestone_row(milestone))


def cmd_activity_log(args, client, config):
    filters = {}
    if args.number is not None:
        filters["issue"] = args.number
    if args.since:
        filters["since"] = parse_since(args.since)
    entries = list(client.activity_log(**filters))
    if args.json:
        print_json(entries)
        return
    for entry in entries:
        print(format_activity_row(entry))


def build_parser():
    parser = argparse.ArgumentParser(prog="pxtx", description="pretalx-tracker CLI")
    parser.add_argument("--json", action="store_true", help="emit raw API JSON")
    parser.add_argument(
        "--actor",
        help=(
            "override the X-Pxtx-Actor header "
            "(default: claude-<branch> inside claude-code, else the token name)"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    issue = sub.add_parser("issue", help="manage issues")
    issue_sub = issue.add_subparsers(dest="subcommand", required=True)

    new = issue_sub.add_parser("new", help="create an issue")
    new.add_argument("--title", required=True)
    new.add_argument("--priority", choices=list(PRIORITY_MAP))
    new.add_argument("--effort", choices=list(EFFORT_MAP))
    new.add_argument("--milestone", help="milestone slug")
    new.add_argument("--description")
    new.add_argument("--assignee")
    new.add_argument(
        "--github-issue",
        dest="github_issue",
        metavar="REF",
        help=(
            "link a GitHub issue after creation: bare number, owner/repo#N, "
            "or github.com/.../issues/N URL"
        ),
    )
    new.set_defaults(func=cmd_issue_new)

    lst = issue_sub.add_parser("list", help="list issues")
    lst.add_argument("--status", help="comma-separated statuses")
    lst.add_argument(
        "--priority",
        type=parse_priority_csv,
        help="comma-separated priority labels (want,should,...)",
    )
    lst.add_argument("--milestone")
    lst.add_argument("--mine", action="store_true", help="filter by current actor")
    lst.add_argument("--assignee")
    lst.add_argument("--highlighted", action="store_true")
    lst.add_argument("--search")
    lst.set_defaults(func=cmd_issue_list)

    show = issue_sub.add_parser("show", help="show an issue")
    show.add_argument("number", type=parse_issue_id, help="PX-47 or 47")
    show.add_argument("--comments", action="store_true")
    show.set_defaults(func=cmd_issue_show)

    close = issue_sub.add_parser("close", help="close an issue")
    close.add_argument("number", type=parse_issue_id)
    close.add_argument("--wontfix", action="store_true")
    close.set_defaults(func=cmd_issue_close)

    comment = issue_sub.add_parser("comment", help="comment on an issue")
    comment.add_argument("number", type=parse_issue_id)
    comment.add_argument("body", nargs="?")
    comment.add_argument("--stdin", action="store_true")
    comment.set_defaults(func=cmd_issue_comment)

    take = sub.add_parser("take", help="claim an issue (assignee=you, status=wip)")
    take.add_argument("number", type=parse_issue_id, help="PX-47 or 47")
    take.set_defaults(func=cmd_issue_take)

    pr = sub.add_parser("pr", help="link a github PR to an issue")
    pr.add_argument("number", type=parse_issue_id, help="PX-47 or 47")
    pr.add_argument(
        "ref",
        help="PR: bare number, owner/repo#N, owner/repo!N, or github.com/.../pull/N URL",
    )
    pr.set_defaults(func=cmd_pr_link)

    issue_ref = sub.add_parser("issue-ref", help="link a github issue to a pxtx issue")
    issue_ref.add_argument("number", type=parse_issue_id, help="PX-47 or 47")
    issue_ref.add_argument(
        "ref",
        help="GH issue: bare number, owner/repo#N, or github.com/.../issues/N URL",
    )
    issue_ref.set_defaults(func=cmd_issue_ref_link)

    interested = sub.add_parser(
        "add-interested", help="add an interested party to an issue"
    )
    interested.add_argument("number", type=parse_issue_id, help="PX-47 or 47")
    interested.add_argument("label")
    interested.add_argument("--url", help="optional link for the party")
    interested.add_argument("--note", help="optional note (shown after the label)")
    interested.set_defaults(func=cmd_add_interested)

    link = sub.add_parser("add-link", help="add a link to an issue")
    link.add_argument("number", type=parse_issue_id, help="PX-47 or 47")
    link.add_argument("label")
    link.add_argument("url")
    link.set_defaults(func=cmd_add_link)

    milestone = sub.add_parser("milestone", help="manage milestones")
    ms_sub = milestone.add_subparsers(dest="subcommand", required=True)
    ms_list = ms_sub.add_parser("list", help="list milestones")
    ms_list.set_defaults(func=cmd_milestone_list)

    activity = sub.add_parser("activity", help="activity log")
    act_sub = activity.add_subparsers(dest="subcommand", required=True)
    act_log = act_sub.add_parser("log", help="show activity log")
    act_log.add_argument("number", type=parse_issue_id, nargs="?")
    act_log.add_argument("--since", help="duration (1h, 2d) or ISO timestamp")
    act_log.set_defaults(func=cmd_activity_log)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    client = Client(config.url, config.token, actor=resolve_actor(args.actor))
    try:
        args.func(args, client, config)
    except CliError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ApiError as exc:
        print(f"api error: {exc}", file=sys.stderr)
        return 1
    return 0

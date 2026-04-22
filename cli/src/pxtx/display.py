from __future__ import annotations

from datetime import datetime

PRIORITY_LABELS = {1: "want", 2: "should", 3: "could", 4: "whatev", 5: "lol"}
EFFORT_LABELS = {30: "<1h", 90: "1-2h", 240: "2-6h", 480: "1d", 960: ">1d"}


def fmt_time(iso_str):
    if not iso_str:
        return "-"
    return datetime.fromisoformat(iso_str).strftime("%Y-%m-%d %H:%M")


def format_priority(value):
    return PRIORITY_LABELS.get(value, str(value))


def format_effort(value):
    if value is None:
        return "-"
    return EFFORT_LABELS.get(value, str(value))


def format_milestone(value):
    if value is None:
        return "-"
    if isinstance(value, dict):
        return value.get("slug") or "-"
    return str(value)


def format_issue_row(issue):
    return "{slug:<7} {status:<9} {priority:<7} {assignee:<20.20} {title}".format(
        slug=issue["slug"],
        status=issue["status"],
        priority=format_priority(issue["priority"]),
        assignee=issue.get("assignee") or "-",
        title=issue["title"],
    )


def format_issue_detail(issue, comments=None):
    lines = [
        f"{issue['slug']}: {issue['title']}",
        "status: {status}  priority: {priority}  effort: {effort}".format(
            status=issue["status"],
            priority=format_priority(issue["priority"]),
            effort=format_effort(issue.get("effort_minutes")),
        ),
        "assignee: {assignee}  milestone: {milestone}".format(
            assignee=issue.get("assignee") or "-",
            milestone=format_milestone(issue.get("milestone")),
        ),
        "created: {created}  updated: {updated}".format(
            created=fmt_time(issue.get("created_at")),
            updated=fmt_time(issue.get("updated_at")),
        ),
    ]
    if issue.get("is_highlighted"):
        lines.append("*highlighted*")
    if issue.get("blocked_reason"):
        lines.append(f"blocked reason: {issue['blocked_reason']}")
    if issue.get("description"):
        lines += ["", issue["description"]]
    if comments is not None:
        lines += ["", f"=== comments ({len(comments)}) ==="]
        for c in comments:
            lines.append(f"[{c['author']} · {fmt_time(c['created_at'])}]")
            lines.append(c["body"])
            lines.append("")
    return "\n".join(lines)


def format_milestone_row(milestone):
    return "{slug:<20} {target:<12} {name}".format(
        slug=milestone["slug"],
        target=milestone.get("target_date") or "-",
        name=milestone["name"],
    )


def format_activity_row(entry):
    return "{time} {actor:<25.25} {action} {ct}#{oid}".format(
        time=fmt_time(entry["timestamp"]),
        actor=entry.get("actor") or "-",
        action=entry["action_type"],
        ct=entry["content_type"],
        oid=entry["object_id"],
    )

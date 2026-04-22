---
name: pxtx
description: >-
  Use the pxtx CLI to read and update pretalx issue tracker tickets (issues,
  comments, milestones). Trigger when the user references a `PX-<number>`
  ticket, asks to list/create/close/comment/take pretalx issues, mentions
  the pretalx tracker, or asks what's assigned to them or pending on
  the tracker.
---

# pxtx — pretalx issue tracker CLI

`pxtx` is the single-user issue tracker for pretalx development. Reach for
this skill whenever the work touches tracker state: reading, creating,
updating, or commenting on issues. The human and other claude instances use
the same tracker, so keep it tidy.

## Invocation

Run via `uvx`, no local install needed:

```
uvx pxtx <subcommand>
```

## Commands

```
pxtx issue new --title "..." [--priority want|should|could|whatev|lol]
                             [--effort <1h|1-2h|2-6h|1d|>1d]
                             [--milestone 25.1] [--description "..."]
                             [--assignee name]
pxtx issue list [--status open,wip,blocked]
                [--priority want,should] [--milestone 25.1]
                [--mine] [--assignee name]
                [--highlighted] [--search "term"]
pxtx issue show PX-47 [--comments]
pxtx issue close PX-47 [--wontfix]
pxtx issue comment PX-47 "message"        # or: --stdin
pxtx take PX-47                           # assignee=you, status=wip
pxtx pr PX-47 <ref>                       # link a GitHub PR
pxtx milestone list
pxtx activity log [PX-47] [--since 1h|2d|1w|<iso>]
```

Top-level flags (before the subcommand):

```
uvx pxtx --json issue show PX-47         # raw API JSON
uvx pxtx --actor rixx issue list --mine  # override the actor
```

## Actor — how the tracker knows which claude is talking

Inside a claude-code session the CLI auto-sends `X-Pxtx-Actor:
claude-<branch>` on every request. That value becomes the ActivityLog
actor and the author of any comments you create — the audit trail always
shows which branch's agent did what, even though every claude instance
shares one API token. Outside claude-code (human on the terminal) the
header is omitted and the server falls back to the token name. Override
explicitly with `--actor NAME` when needed.

`--mine` filters issues by that resolved actor, and `pxtx take PX-47`
sets the issue assignee to the same value (plus moves it to `wip`), so
picking up work is one command.

## Conventions to follow

- **Ids are `PX-<number>`** everywhere in tickets and commit messages.
- **Leave a comment when you do nontrivial work.** Closing a ticket is not
  a summary — add context to the ticket so the next person (human or
  agent) sees what happened. `uvx pxtx issue comment PX-47 --stdin`
  accepts multi-line markdown.
  Your comments should be terse – they will be read by domain experts,
  i.e. users who know the code base and issue very well, and other
  coding agents with the same knowledge base as you have. Do not state
  the obvious.
- **Check before creating.** Before filing a new issue, run
  `uvx pxtx issue list --search "<keywords>"` so you don't duplicate an
  existing one (including `draft` ghost issues pulled from GitHub).
- **`blocked` needs a reason.** If you move an issue to `blocked`, include
  a `--description`-style explanation in a comment — the UI requires it
  and humans rely on it.
- **Open a PR? Link it immediately.** The moment you push a branch and
  open a pull request for work tracked by a `PX-<n>` issue, run
  `uvx pxtx pr PX-<n> <pr>` so the tracker shows the PR alongside the
  issue. The call is idempotent — re-running it with the same PR is a
  no-op, so you can wire it into your PR-opening flow without worrying
  about duplicates. `<pr>` can be a bare number (uses `default_repo`),
  `owner/repo#N`, or a `github.com/.../pull/N` URL.

## Typical flows

**"What should I work on?"**

```
uvx pxtx issue list --mine --status open,wip
uvx pxtx issue list --highlighted
uvx pxtx issue list --priority want,should --status open
```

**"I'll take this one."** Claim it (assigns to you + moves to wip) in one shot:

```
uvx pxtx take PX-47
```

**"I opened a PR for this."** Link it right after `gh pr create`:

```
gh pr create ...                          # whatever you'd run normally
uvx pxtx pr PX-47 https://github.com/pretalx/pretalx/pull/9912
# or: uvx pxtx pr PX-47 pretalx/pretalx#9912
```

**"Close this one, I shipped it."** Add a closing comment, then close:

```
uvx pxtx issue comment PX-47 "Shipped in pretalx/pretalx#9912."
uvx pxtx issue close PX-47
```

For abandoned work use `--wontfix` instead of `close`. Do not close issues
silently; the comment is the audit trail.

**"File a bug for this."** Search first, then create:

```
uvx pxtx issue list --search "rate limit"
uvx pxtx issue new --title "..." --priority should --description "$(cat <<'EOF'
Steps to reproduce
...
EOF
)"
```

**"What happened on PX-47 recently?"**

```
uvx pxtx --json issue show PX-47 --comments
uvx pxtx activity log PX-47 --since 7d
```

## When things fail

- `error: config ...` — CLI can't find URL/token. Stop and ask the user.
- `api error: 401` — token rejected. Do not retry. Stop and report.
- `api error: 404` — wrong issue number or you mistyped the slug. Verify
  with `uvx pxtx issue list --search "<title fragment>"`.
- `api error: 400` with a field name — the API validated the payload and
  rejected it; read the message, fix the field, retry.

---
name: pxtx
description: >-
  Use the pxtx CLI to read and update pretalx issue tracker tickets (issues,
  comments, milestones). Trigger when the user references a `PX-<number>`
  ticket, asks to list/create/close/comment/take pretalx issues, mentions
  the pretalx tracker, or asks what's assigned to them or pending on
  the tracker. Also trigger when asked to pull or implement a ready
  spec session (`pxtx spec pull`), or to push a locally developed
  spec into an issue's spec session (`pxtx spec push`).
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
pxtx issue new --title "..." [--priority jetzt|will|sollte|könnte|egal|lol]
                             [--effort <1h|1-2h|2-6h|1d|>1d]
                             [--milestone 25.1] [--description "..."]
                             [--assignee name]
                             [--github-issue <ref>]
pxtx issue list [--status open,wip,blocked]
                [--priority will,sollte] [--milestone 25.1]
                [--mine] [--assignee name]
                [--highlighted] [--search "term"]
pxtx issue show PX-47 [--comments]        # or: pxtx show PX-47
pxtx issue set PX-47 [--priority will] [--effort 2-6h]   # narrow edit
pxtx issue close PX-47 [--wontfix]
pxtx issue comment PX-47 "message"        # or: --stdin
pxtx take PX-47                           # assignee=you, status=wip
pxtx pr PX-47 <ref>                       # link a GitHub PR
pxtx issue-ref PX-47 <ref>                # link a GitHub issue
pxtx add-interested PX-47 "Name" [--url URL] [--note "..."]
pxtx add-link PX-47 "label" <url>
pxtx milestone list
pxtx activity log [PX-47] [--since 1h|2d|1w|<iso>]
pxtx spec pull PX-47 [--force]            # materialize ready spec artifacts
pxtx spec push PX-47 [--message "..."] [--ready] [--reopen]
                     [--change NAME]      # send a local spec to the session
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
uvx pxtx issue list --priority jetzt,will,sollte --status open
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

**"Bump priority / effort on a ticket."** `issue set` is the only edit
path — title, description, assignee, and milestone are off-limits to the
CLI by design:

```
uvx pxtx issue set PX-47 --priority jetzt
uvx pxtx issue set PX-47 --effort 2-6h
uvx pxtx issue set PX-47 --priority will --effort 1-2h
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
uvx pxtx issue new --title "..." --priority sollte --description "$(cat <<'EOF'
Steps to reproduce
...
EOF
)"
```

Report the resulting issue number to the user.

**"Make a pxtx issue from this GitHub issue."** Create and link in one
call — the `--github-issue` flag takes the same ref forms as `issue-ref`
(bare number uses `default_repo`, `owner/repo#N`, or a
`github.com/.../issues/N` URL):

```
uvx pxtx issue new --title "..." --priority sollte \
    --github-issue pretalx/pretalx#9912
```

If the ticket already exists, attach the GitHub issue after the fact:

```
uvx pxtx issue-ref PX-47 pretalx/pretalx#9912
# or: uvx pxtx issue-ref PX-47 https://github.com/pretalx/pretalx/issues/9912
```

Like `pxtx pr`, the call is idempotent on `(kind, repo, number)` — a
re-run with the same ref is a no-op rather than a duplicate row.

**"Record who cares / what to read."** Append to an issue's side metadata
without a full edit — both commands are idempotent on `(label, url)`, so
re-running is a no-op:

```
uvx pxtx add-interested PX-47 "Speaker X" --url mailto:x@example.com \
                                          --note "reported via email"
uvx pxtx add-link PX-47 "RFC" https://example.com/rfc
```

Use `add-interested` for humans/stakeholders (url + note are optional;
url can be a `mailto:` or anything else) and `add-link` for references
(spec, doc, related thread). Neither supports edit/remove — drop into
the Django admin for that.

**"The spec for PX-47 is ready — implement it."** Spec sessions are
written by a server-side agent and reviewed in the pxtx UI; once the
human marks a session *ready*, pull its OpenSpec artifacts into your
local checkout. Run it from the repo root — files land under
`openspec/changes/pxtx-47/` relative to your current directory:

```
uvx pxtx spec pull PX-47
```

Files that already match the snapshot are skipped silently. If a
target file differs locally, the command refuses, lists the conflicting
files, writes nothing, and exits non-zero — re-run with `--force` to
overwrite them with the snapshot. If there is nothing to pull (the issue
has no spec session, or no finished turn produced artifacts yet), it
also exits non-zero and says so. After pulling, implement the change
like any other OpenSpec change directory.

**"I wrote a spec locally — get it into the tracker."** The reverse of
`spec pull`: push everything under `openspec/changes/pxtx-47/` (relative
to cwd, dotfiles included, text files only) into PX-47's spec session as
a new transcript entry. Run it from the repo root:

```
uvx pxtx spec push PX-47 --message "first draft, focus on the API shape"
```

The issue does not need an existing spec session — pushing creates one
at stage `propose`. If the spec lives under a different local change
name, `--change NAME` reads `openspec/changes/NAME/` instead (the
server-side directory is still named after the issue). Pushing identical
content twice is a no-op (exit 0, "nothing pushed"), so re-pushing after
every edit is safe.

The push-then-iterate loop: push a draft, then let the server-side
session do the reviewing — in the pxtx UI, request a critique or chat
with the spec agent about it, and `uvx pxtx spec pull PX-47 --force`
later to converge your checkout on the reviewed result. When the spec is
actually finished, push with `--ready` to mark the session ready in the
same call. A session already marked `ready` rejects pushes (409) unless
you pass `--reopen`, which deliberately un-readies it first — don't do
that unless the human asked for the spec to change.

Failure modes: a missing or empty change directory exits non-zero
("nothing to push"), as does a non-UTF-8 file (binaries never belong in
a spec). A 409 means the session is busy (a turn is queued or running —
retry once it finishes) or `ready` without `--reopen`; a 400 names the
offending file or field.

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

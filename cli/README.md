# pxtx

Command-line client for [pxtx](https://github.com/pretalx/pxtx), the pretalx
issue tracker. Talks to the REST API over HTTP; pairs equally well with a
human at the keyboard and a claude-code instance.

## Install

```
pip install pxtx
```

## Configure

Create `~/.config/pxtx/config.toml`:

```toml
url = "https://tracker.pretalx.com"
token = "pxtx_..."
# Repo assumed when a GitHub reference is specified without a repo (e.g. GH-42).
default_repo = "pretalx/pretalx"
```

Any of these can also be supplied via environment variables: `PXTX_URL`,
`PXTX_TOKEN`, `PXTX_DEFAULT_REPO`, `PXTX_CONFIG` (path override).

## Commands

```
pxtx issue new --title "..." [--priority sollte] [--effort 2-6h] [--milestone 25.1]
pxtx issue list [--status open,wip] [--mine] [--priority will,sollte]
pxtx issue show PX-47 [--comments]
pxtx issue close PX-47 [--wontfix]
pxtx issue comment PX-47 "message"    # or --stdin
pxtx take PX-47                       # assignee=you, status=wip
pxtx pr PX-47 <ref>                   # link a GitHub PR (idempotent)
pxtx milestone list
pxtx activity log [PX-47] [--since 1h]
```

Append `--json` (as a top-level flag, e.g. `pxtx --json issue show PX-47`) to
get the raw API response instead of a human-readable summary.

## Actor

The server records an `actor` alongside every API action (activity log,
comment authorship). When run inside a claude-code session
(`CLAUDECODE=1`), the CLI auto-derives `claude-<git-branch>` and sends it
as `X-Pxtx-Actor` on every request, so a single shared API token can
still attribute work to the right agent. Outside claude-code the header
is omitted and the server falls back to the token name. Override
explicitly with `--actor NAME` before the subcommand:

```
pxtx --actor rixx issue list --mine
```

`--mine` and `pxtx take` both use this resolved actor.

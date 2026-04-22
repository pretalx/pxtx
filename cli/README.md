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
# Used by --mine to filter issues by assignee. Should match the name your API
# token was created with in the Django admin.
actor = "claude/feature-xyz"
# Repo assumed when a GitHub reference is specified without a repo (e.g. GH-42).
default_repo = "pretalx/pretalx"
```

Any of these can also be supplied via environment variables: `PXTX_URL`,
`PXTX_TOKEN`, `PXTX_ACTOR`, `PXTX_DEFAULT_REPO`, `PXTX_CONFIG` (path override).

## Commands

```
pxtx issue new --title "..." [--priority want] [--effort 2-6h] [--milestone 25.1]
pxtx issue list [--status open,wip] [--mine [--branch]] [--priority want]
pxtx issue show PX-47 [--comments]
pxtx issue close PX-47 [--wontfix]
pxtx issue comment PX-47 "message"    # or --stdin
pxtx milestone list
pxtx activity log [PX-47] [--since 1h]
```

Append `--json` (as a top-level flag, e.g. `pxtx --json issue show PX-47`) to
get the raw API response instead of a human-readable summary.

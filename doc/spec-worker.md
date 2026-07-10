# Spec worker: server prerequisites

`manage.py runworker` (the spec-session worker, see the "Spec sessions"
section in [`CLAUDE.md`](../CLAUDE.md)) only defines the invocation
contract; everything it invokes must already be on the server. Provisioning
lives in the ansible repo — this note is the checklist of what that side
has to provide. The feature is inert until the `[spec]` section of
`pxtx.toml` exists, so pxtx itself is always safe to deploy first.

## Checkout

- A pretalx checkout at `[spec] checkout_path`, writable by the worker
  user, with openspec initialized (`openspec/` present). The worker runs
  every `claude -p` turn with this directory as cwd; claude sessions are
  bound to the cwd they were created in, so moving the checkout makes all
  existing sessions unresumable.
- The worker keeps the checkout fresh with an idle
  `git pull --ff-only`, which never touches the untracked
  `openspec/changes/` directories. The agent itself is denied git writes
  (see the settings file below), so this pull is the only way the checkout
  advances.

## Claude

- The claude binary from `[spec] claude_binary` (default: `claude` on
  PATH) must be installed and authenticated for the worker user — the
  worker never handles credentials.
- A deployed agent settings file at `[spec] settings_file`, passed via
  `--settings`. It must deny git write commands: the checkout is shared
  across sessions, and an agent running destructive git would wipe other
  sessions' uncommitted change directories. Beware that claude *silently
  ignores* settings files that fail validation — that is why the worker
  logs a warning before each run when the file is missing or not valid
  JSON, and why deploy-time validation belongs in ansible. The per-turn
  budget cap is passed as a CLI flag (`--max-budget-usd`), so it holds
  even when the settings file is broken.
- The `/opsx:*` command definitions (openspec tooling) must be available
  to claude in the checkout — the worker's prompts start with
  `/opsx:explore` / `/opsx:propose` and fail without them.

## Systemd

- The worker runs as a long-lived systemd service, and its
  single-instance guarantee is load-bearing: on startup the worker
  requeues all `running` turns, which would clobber a second live
  worker's in-flight turn. Never run two instances against one database.
- The deploy pipeline must restart `runworker` together with the web
  process — the worker runs pxtx model code and cannot outlive a
  migration. Restarting mid-turn is safe by construction: systemd kills
  the cgroup including the in-flight claude subprocess, the startup
  requeue flips the turn back to `queued`, and the re-run resumes the
  claude session; the only cost is re-paying for the interrupted turn's
  context.

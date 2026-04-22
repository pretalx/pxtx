# pxtx

Single-user issue tracker for [pretalx](https://pretalx.com) development
with a web interface and a CLI, published as `pxtx` to PyPI to be run
with `uvx`.

## Server

```bash
just install-all          # install deps
just run migrate          # apply migrations
just run createsuperuser  # mint an admin account
just run                  # dev server on :8000
```

Optional config lives in `/etc/pxtx.toml` (prod) or `pxtx.toml` next to
`pyproject.toml` (dev); see [`pxtx.toml.example`](pxtx.toml.example) for the
GitHub polling settings.

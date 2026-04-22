from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "pxtx" / "config.toml"


class ConfigError(Exception):
    pass


@dataclass
class Config:
    url: str
    token: str
    default_repo: str = "pretalx/pretalx"


def load_config(path: Path | None = None) -> Config:
    if path is None:
        env_path = os.environ.get("PXTX_CONFIG")
        path = Path(env_path) if env_path else DEFAULT_CONFIG_PATH

    data: dict = {}
    if path.exists():
        try:
            data = tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"invalid toml in {path}: {exc}") from exc

    url = os.environ.get("PXTX_URL") or data.get("url")
    token = os.environ.get("PXTX_TOKEN") or data.get("token")
    if not url:
        raise ConfigError(f"missing 'url' (set it in {path} or PXTX_URL)")
    if not token:
        raise ConfigError(f"missing 'token' (set it in {path} or PXTX_TOKEN)")

    return Config(
        url=url.rstrip("/"),
        token=token,
        default_repo=(
            os.environ.get("PXTX_DEFAULT_REPO")
            or data.get("default_repo", "pretalx/pretalx")
        ),
    )

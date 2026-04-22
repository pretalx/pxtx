from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
import responses

from pxtx.client import Client
from pxtx.config import Config

if TYPE_CHECKING:
    from pathlib import Path

TEST_URL = "https://tracker.example.test"
TEST_TOKEN = "pxtx_test"
TEST_ACTOR = "claude/test"


@pytest.fixture(autouse=True)
def _clean_pxtx_env(monkeypatch):
    for name in (
        "PXTX_URL",
        "PXTX_TOKEN",
        "PXTX_ACTOR",
        "PXTX_DEFAULT_REPO",
        "PXTX_CONFIG",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def config():
    return Config(url=TEST_URL, token=TEST_TOKEN, actor=TEST_ACTOR)


@pytest.fixture
def client(config):
    return Client(config.url, config.token)


@pytest.fixture
def mocked_responses():
    with responses.RequestsMock() as rsps:
        yield rsps


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch):
    path = tmp_path / "config.toml"
    monkeypatch.setenv("PXTX_CONFIG", str(path))
    return path


@pytest.fixture
def cli_config(config_file, monkeypatch):
    config_file.write_text(
        f'url = "{TEST_URL}"\ntoken = "{TEST_TOKEN}"\nactor = "{TEST_ACTOR}"\n'
    )
    return config_file

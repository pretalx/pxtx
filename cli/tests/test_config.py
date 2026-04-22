from __future__ import annotations

import pytest

from pxtx.config import Config, ConfigError, load_config


def test_load_config_reads_all_fields(config_file):
    config_file.write_text(
        'url = "https://example.test"\n'
        'token = "pxtx_abc"\n'
        'default_repo = "acme/widget"\n'
    )

    config = load_config()

    assert config == Config(
        url="https://example.test", token="pxtx_abc", default_repo="acme/widget"
    )


def test_load_config_strips_trailing_url_slash(config_file):
    config_file.write_text('url = "https://example.test/"\ntoken = "pxtx_abc"\n')

    assert load_config().url == "https://example.test"


def test_load_config_defaults_repo(config_file):
    config_file.write_text('url = "https://example.test"\ntoken = "pxtx_abc"\n')

    assert load_config().default_repo == "pretalx/pretalx"


def test_load_config_explicit_path_wins_over_env(tmp_path, monkeypatch):
    env_path = tmp_path / "env.toml"
    env_path.write_text('url = "http://env"\ntoken = "env"\n')
    monkeypatch.setenv("PXTX_CONFIG", str(env_path))

    explicit = tmp_path / "explicit.toml"
    explicit.write_text('url = "http://explicit"\ntoken = "explicit"\n')

    config = load_config(path=explicit)

    assert config.url == "http://explicit"


def test_load_config_missing_url_raises(config_file):
    config_file.write_text('token = "pxtx_abc"\n')

    with pytest.raises(ConfigError, match="url"):
        load_config()


def test_load_config_missing_token_raises(config_file):
    config_file.write_text('url = "https://example.test"\n')

    with pytest.raises(ConfigError, match="token"):
        load_config()


def test_load_config_invalid_toml_raises(config_file):
    config_file.write_text("not = valid = toml")

    with pytest.raises(ConfigError, match="invalid toml"):
        load_config()


def test_load_config_missing_file_without_env_raises(tmp_path):
    missing = tmp_path / "nope.toml"

    with pytest.raises(ConfigError):
        load_config(path=missing)


def test_load_config_env_vars_override(config_file, monkeypatch):
    config_file.write_text(
        'url = "https://file"\ntoken = "file-token"\ndefault_repo = "file/repo"\n'
    )
    monkeypatch.setenv("PXTX_URL", "https://env/")
    monkeypatch.setenv("PXTX_TOKEN", "env-token")
    monkeypatch.setenv("PXTX_DEFAULT_REPO", "env/repo")

    config = load_config()

    assert config.url == "https://env"
    assert config.token == "env-token"
    assert config.default_repo == "env/repo"


def test_load_config_from_env_only(monkeypatch, tmp_path):
    monkeypatch.setenv("PXTX_URL", "https://env.test")
    monkeypatch.setenv("PXTX_TOKEN", "env-token")

    missing = tmp_path / "absent.toml"
    config = load_config(path=missing)

    assert config.url == "https://env.test"
    assert config.token == "env-token"
    assert config.default_repo == "pretalx/pretalx"

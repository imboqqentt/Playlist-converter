import os

import pytest

from playlist_converter import cli, config


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for name in config.REQUIRED_VARS:
        monkeypatch.delenv(name, raising=False)
    return tmp_path


@pytest.mark.parametrize("filename", [".env", ".env.txt"])
def test_load_env_file(clean_env, filename):
    # BOM + comillas + comentarios + "export", como lo dejaría el Bloc de notas o un Mac.
    (clean_env / filename).write_text(
        '﻿# comentario\nSPOTIPY_CLIENT_ID = "abc"\nexport SPOTIPY_CLIENT_SECRET=xyz\n\n',
        encoding="utf-8",
    )
    assert config.load_env_file(clean_env).name == filename
    assert os.environ["SPOTIPY_CLIENT_ID"] == "abc"
    assert os.environ["SPOTIPY_CLIENT_SECRET"] == "xyz"
    assert config.missing_vars() == []


def test_env_file_does_not_override_existing_vars(clean_env, monkeypatch):
    monkeypatch.setenv("SPOTIPY_CLIENT_ID", "from_shell")
    (clean_env / ".env").write_text("SPOTIPY_CLIENT_ID=from_file\n")
    config.load_env_file(clean_env)
    assert os.environ["SPOTIPY_CLIENT_ID"] == "from_shell"


def test_cli_explains_missing_credentials(clean_env, capsys):
    (clean_env / "browser.json").write_text("{}")
    code = cli.main(["convert", "liked"])
    assert code == 2
    err = capsys.readouterr().err
    assert "SPOTIPY_CLIENT_ID" in err and ".env" in err

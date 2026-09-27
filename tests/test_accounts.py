import pytest

from playlist_converter import accounts, cli, interactive
from playlist_converter.ytmusic_target import YTMusicTarget

HEADERS = "cookie: SAPISID=abc; __Secure-3PAPISID=abc\nx-goog-authuser: 0\nuser-agent: Mozilla/5.0"


def test_clean_name():
    assert accounts.clean_name("  Mamá López ") == "Mamá_López"
    with pytest.raises(ValueError):
        accounts.clean_name(" / ")


def test_save_list_and_remove_accounts(isolated_app_dir):
    accounts.save_account("daniel", HEADERS)
    accounts.save_account("mama", HEADERS)
    assert accounts.list_accounts() == ["daniel", "mama"]
    assert (isolated_app_dir / "cuentas" / "daniel.json").exists()
    assert accounts.remove_account("mama") is True
    assert accounts.remove_account("mama") is False
    assert accounts.list_accounts() == ["daniel"]


def test_save_account_rejects_headers_without_cookie():
    with pytest.raises(Exception):
        accounts.save_account("x", "user-agent: Mozilla/5.0")


def test_read_headers_stops_at_blank_line_or_eof():
    lines = iter(["", "a: 1", "b: 2", "", "ignored"])
    assert accounts.read_headers(lambda _: next(lines)) == "a: 1\nb: 2"

    def eof_after_one():
        yield "a: 1"
        raise EOFError

    gen = eof_after_one()
    assert accounts.read_headers(lambda _: next(gen)) == "a: 1"


def test_resolve_auth(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="No hay ninguna cuenta"):
        accounts.resolve_auth(None, None)

    (tmp_path / "browser.json").write_text("{}")
    assert accounts.resolve_auth(None, None).name == "browser.json"  # versión anterior

    accounts.save_account("daniel", HEADERS)
    assert accounts.resolve_auth(None, None).stem == "daniel"  # única cuenta
    accounts.save_account("mama", HEADERS)
    with pytest.raises(ValueError, match="varias cuentas"):
        accounts.resolve_auth(None, None)
    assert accounts.resolve_auth("mama", None).stem == "mama"
    with pytest.raises(ValueError, match="No existe la cuenta"):
        accounts.resolve_auth("otra", None)


def test_cli_accounts_commands(capsys):
    accounts.save_account("daniel", HEADERS)
    assert cli.main(["accounts"]) == 0
    assert "- daniel" in capsys.readouterr().out
    assert cli.main(["remove-account", "daniel"]) == 0
    assert cli.main(["remove-account", "daniel"]) == 2


def test_cli_add_account_reads_pasted_headers(monkeypatch):
    lines = iter(HEADERS.splitlines() + [""])
    monkeypatch.setattr("builtins.input", lambda _="": next(lines))
    assert cli.main(["add-account", "trabajo"]) == 0
    assert accounts.list_accounts() == ["trabajo"]


def scripted(answers):
    it = iter(answers)
    return lambda _="": next(it)


def test_menu_adds_account_then_exits():
    ask = scripted(["2", "Mamá", *HEADERS.splitlines(), "", "4"])
    assert interactive.run_menu(ask) == 0
    assert accounts.list_accounts() == ["Mamá"]


def test_menu_convert_builds_expected_command(monkeypatch):
    accounts.save_account("daniel", HEADERS)
    accounts.save_account("mama", HEADERS)
    seen = {}
    monkeypatch.setattr(interactive, "cmd_convert", lambda args: seen.update(vars(args)) or 0)

    link = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
    ask = scripted(["1", "2", link, "Viaje", "2", "s", "", "4"])
    assert interactive.run_menu(ask) == 0
    assert seen["account"] == "mama"
    assert seen["playlist"] == link
    assert seen["name"] == "Viaje"
    assert seen["privacy"] == "UNLISTED"
    assert seen["dry_run"] is True


def test_menu_survives_errors(monkeypatch, capsys):
    accounts.save_account("daniel", HEADERS)

    def boom(args):
        raise RuntimeError("se cayó internet")

    monkeypatch.setattr(interactive, "cmd_convert", boom)
    link = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"
    ask = scripted(["1", link, "", "", "n", "4"])
    assert interactive.run_menu(ask) == 0
    assert "se cayó internet" in capsys.readouterr().out


def test_convert_uses_selected_account(tmp_path, monkeypatch):
    accounts.save_account("daniel", HEADERS)
    accounts.save_account("mama", HEADERS)
    monkeypatch.setenv("SPOTIPY_CLIENT_ID", "id")
    monkeypatch.setenv("SPOTIPY_CLIENT_SECRET", "secret")
    used = {}

    def fake_from_auth_file(cls, path, delay=0):
        used["path"] = path
        raise SystemExit(0)

    monkeypatch.setattr(YTMusicTarget, "from_auth_file", classmethod(fake_from_auth_file))
    monkeypatch.setattr("playlist_converter.cli.SpotifySource.from_env", classmethod(lambda cls: None))
    with pytest.raises(SystemExit):
        cli.main(["convert", "liked", "--account", "mama"])
    assert used["path"].endswith("mama.json")

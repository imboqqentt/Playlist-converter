import pytest
from fakes import FakeService, track

from playlist_converter import accounts, cli, links, services

HEADERS = "cookie: SAPISID=abc; __Secure-3PAPISID=abc\nx-goog-authuser: 0\nuser-agent: Mozilla/5.0"
YT_LINK = "https://music.youtube.com/playlist?list=PLyt123"
SP_LINK = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPOTIPY_CLIENT_ID", "id")
    monkeypatch.setenv("SPOTIPY_CLIENT_SECRET", "secret")
    spotify = FakeService(
        "spotify",
        playlists={"37i9dQZF1DXcBWIGoYBM5M": [track("A"), track("B")]},
        catalog={"Y1": "sp1", "Y2": "sp2", "Y3": "sp3"},
        names={"37i9dQZF1DXcBWIGoYBM5M": "Lista Spotify"},
    )
    ytmusic = FakeService(
        "ytmusic",
        playlists={"PLyt123": [track("Y1"), track("Y2")]},
        catalog={"A": "yA", "B": "yB", "C": "yC"},
        names={"PLyt123": "Lista YT"},
    )
    auth_seen = []

    def fake_yt(auth_path, delay=0.0):
        auth_seen.append(auth_path)
        return ytmusic

    monkeypatch.setattr(services, "default_spotify_factory", lambda: spotify)
    monkeypatch.setattr(services, "default_ytmusic_factory", fake_yt)
    return {"spotify": spotify, "ytmusic": ytmusic, "auth": auth_seen}


def test_convert_youtube_to_spotify_without_account(world, capsys):
    # Leer una playlist pública de YouTube Music no requiere cuenta.
    assert cli.main(["convert", YT_LINK]) == 0
    assert world["spotify"].created == [("Lista YT", "PRIVATE")]
    assert world["spotify"].playlist_item_ids("new1") == ["sp1", "sp2"]
    assert world["auth"] == [None]  # solo se usó para leer, sin sesión
    out = capsys.readouterr().out
    assert "YouTube Music → Spotify" in out
    saved = links.load()
    assert len(saved) == 1 and saved[0].source_service == "ytmusic" and saved[0].account is None


def test_convert_spotify_to_youtube_requires_account(world, capsys):
    assert cli.main(["convert", SP_LINK]) == 2
    assert "No hay ninguna cuenta" in capsys.readouterr().err
    accounts.save_account("daniel", HEADERS)
    assert cli.main(["convert", SP_LINK]) == 0
    assert world["ytmusic"].playlist_item_ids("new1") == ["yA", "yB"]
    assert links.load()[0].account == "daniel"


def test_limit_and_dry_run_do_not_save_sync(world):
    accounts.save_account("daniel", HEADERS)
    assert cli.main(["convert", SP_LINK, "--dry-run"]) == 0
    assert cli.main(["convert", SP_LINK, "--limit", "1"]) == 0
    assert links.load() == []


def test_synced_update_and_unlink(world, capsys):
    accounts.save_account("daniel", HEADERS)
    cli.main(["convert", SP_LINK])
    link_id = links.load()[0].id
    capsys.readouterr()

    assert cli.main(["synced"]) == 0
    assert link_id in capsys.readouterr().out

    world["spotify"].playlists["37i9dQZF1DXcBWIGoYBM5M"] = [track("A"), track("C")]  # sale B, entra C
    assert cli.main(["update", link_id, "--remove-missing"]) == 0
    out = capsys.readouterr().out
    assert "Agregadas: 1. Quitadas: 1." in out
    assert world["ytmusic"].playlist_item_ids("new1") == ["yA", "yC"]

    assert cli.main(["update"]) == 2  # sin IDs ni --all
    assert cli.main(["update", "nope"]) == 2
    assert cli.main(["update", "--all"]) == 0
    assert cli.main(["unlink", link_id]) == 0
    assert cli.main(["unlink", link_id]) == 2


def test_link_existing_then_update(world, capsys):
    accounts.save_account("daniel", HEADERS)
    existing = "SPexisting000000000000"  # los IDs de Spotify tienen 22 caracteres
    world["spotify"].playlists[existing] = [track("sp1", key="sp1")]
    assert cli.main(["link", YT_LINK, f"https://open.spotify.com/playlist/{existing}"]) == 0
    link = links.load()[0]
    assert (link.source_name, link.target_id, link.account) == ("Lista YT", existing, "daniel")
    assert cli.main(["update", link.id]) == 0
    # Y1 ya estaba (sp1): solo se agrega Y2
    assert world["spotify"].playlist_item_ids(existing) == ["sp1", "sp2"]


def test_link_rejects_same_service(world, capsys):
    accounts.save_account("daniel", HEADERS)
    assert cli.main(["link", SP_LINK, SP_LINK]) == 2
    assert "servicios distintos" in capsys.readouterr().err

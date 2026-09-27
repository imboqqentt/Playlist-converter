import os
import time

import pytest

tk = pytest.importorskip("tkinter")

from playlist_converter import accounts  # noqa: E402
from playlist_converter.models import Candidate, MatchResult, MatchStatus, Track  # noqa: E402

HEADERS = "cookie: SAPISID=abc; __Secure-3PAPISID=abc\nx-goog-authuser: 0\nuser-agent: Mozilla/5.0"
LINK = "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"


def test_friendly_error_messages():
    from playlist_converter.gui import friendly_error

    assert "Client ID" in friendly_error(Exception("error: invalid_client"))
    assert "Discover Weekly" in friendly_error(Exception("http status: 404, code:-1"))
    assert friendly_error(RuntimeError("otra cosa")) == "otra cosa"


class FakeSpotify:
    def __init__(self, n=3):
        self.n = n

    def playlist_name(self, pid):
        return "Mi Playlist"

    def tracks(self, pid):
        for i in range(self.n):
            yield Track(f"Song {i}", ("Artist",), 200)


class FakeYT:
    def __init__(self, delay=0.0):
        self.delay = delay
        self.created = []
        self.added = []

    def find(self, track):
        time.sleep(self.delay)
        if track.title.endswith("2"):
            return MatchResult(track, MatchStatus.NOT_FOUND, None, 0.2)
        return MatchResult(track, MatchStatus.MATCHED, Candidate("v" + track.title[-1], track.title, ("Artist",), 200), 0.95)

    def create_playlist(self, name, description, privacy):
        self.created.append((name, privacy))
        return "PL1"

    def add_videos(self, pid, ids):
        self.added.append((pid, ids))


@pytest.fixture
def app_factory(monkeypatch):
    from playlist_converter import gui

    monkeypatch.setenv("SPOTIPY_CLIENT_ID", "id")
    monkeypatch.setenv("SPOTIPY_CLIENT_SECRET", "secret")
    dialogs = []
    for kind in ("showwarning", "showerror", "showinfo"):
        monkeypatch.setattr(gui.messagebox, kind, lambda *a, _k=kind, **kw: dialogs.append((_k, a)))
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **kw: False)
    created = []

    def make(spotify=None, yt=None):
        try:
            app = gui.App(spotify_factory=lambda: spotify or FakeSpotify(), ytmusic_factory=lambda p: yt or FakeYT())
        except tk.TclError as exc:
            pytest.skip(f"sin pantalla: {exc}")
        app.withdraw()
        app.dialogs = dialogs
        created.append(app)
        return app

    yield make
    for app in created:
        app.destroy()


def run_until_idle(app, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.update()
        if not (app.worker and app.worker.is_alive()) and app.events.empty():
            app.update()
            return
        time.sleep(0.02)
    raise AssertionError("la conversión no terminó")


def test_full_conversion(app_factory):
    accounts.save_account("daniel", HEADERS)
    yt = FakeYT()
    app = app_factory(yt=yt)
    app.link_entry.set_value(LINK)
    app.privacy_var.set("UNLISTED")
    app.start()
    run_until_idle(app)

    assert len(app.tree.get_children()) == 3
    assert yt.created == [("Mi Playlist", "UNLISTED")]
    assert yt.added == [("PL1", ["v0", "v1"])]
    assert "2 canciones agregadas" in app.status_var.get()
    assert str(app.open_btn["state"]) == "normal"
    assert "1 no encontradas" in app.summary_var.get()


def test_dry_run_does_not_create_playlist(app_factory):
    accounts.save_account("daniel", HEADERS)
    yt = FakeYT()
    app = app_factory(yt=yt)
    app.link_entry.set_value(LINK)
    app.dry_run_var.set(True)
    app.start()
    run_until_idle(app)
    assert yt.created == []
    assert str(app.open_btn["state"]) == "disabled"
    assert "Prueba terminada" in app.status_var.get()


def test_cancel_stops_before_touching_youtube(app_factory):
    accounts.save_account("daniel", HEADERS)
    yt = FakeYT(delay=0.2)
    app = app_factory(spotify=FakeSpotify(n=20), yt=yt)
    app.link_entry.set_value(LINK)
    app.start()
    app.cancel()
    run_until_idle(app)
    assert yt.created == []
    assert "Cancelado" in app.status_var.get()


def test_validation_requires_link_and_account(app_factory):
    app = app_factory()
    app.start()
    assert app.dialogs[-1][0] == "showwarning"  # falta el link
    app.link_entry.set_value(LINK)
    app.start()  # no hay cuentas: pregunta si agregar una (respondemos que no)
    assert app.worker is None


def test_errors_are_shown_in_a_dialog(app_factory):
    accounts.save_account("daniel", HEADERS)

    class Broken(FakeSpotify):
        def playlist_name(self, pid):
            raise Exception("error: invalid_client")

    app = app_factory(spotify=Broken())
    app.link_entry.set_value(LINK)
    app.start()
    run_until_idle(app)
    kind, args = app.dialogs[-1]
    assert kind == "showerror" and "Client ID" in args[1]
    assert str(app.convert_btn["state"]) == "normal"


def test_liked_songs_skip_link(app_factory):
    accounts.save_account("daniel", HEADERS)
    app = app_factory()
    app.liked_var.set(True)
    assert app.validate()[0] == "liked"


def test_add_account_dialog(app_factory):
    from playlist_converter.gui import AddAccountDialog

    app = app_factory()
    dialog = AddAccountDialog(app)
    dialog.name_entry.set_value("mamá")
    dialog.text.insert("1.0", HEADERS)
    dialog.save()
    assert accounts.list_accounts() == ["mamá"]
    assert app.account_var.get() == "mamá"

    bad = AddAccountDialog(app)
    bad.name_entry.set_value("otra")
    bad.text.insert("1.0", "user-agent: x")
    bad.save()
    assert app.dialogs[-1][0] == "showerror"
    assert "otra" not in accounts.list_accounts()
    bad.destroy()


def test_spotify_settings_dialog_saves_credentials(app_factory, isolated_app_dir):
    from playlist_converter.gui import SpotifySettingsDialog

    app = app_factory()
    dialog = SpotifySettingsDialog(app)
    dialog.id_var.set(" nuevo_id ")
    dialog.secret_var.set("nuevo_secret")
    dialog.save()
    assert dialog.saved
    assert os.environ["SPOTIPY_CLIENT_ID"] == "nuevo_id"
    assert "nuevo_secret" in (isolated_app_dir / ".env").read_text()

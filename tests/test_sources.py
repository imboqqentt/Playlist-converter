import pytest

from playlist_converter import cli
from playlist_converter.models import MatchStatus, Track
from playlist_converter.spotify_source import LIKED, SpotifySource, parse_playlist_ref, parse_track
from playlist_converter.ytmusic_target import YTMusicTarget

PID = "37i9dQZF1DXcBWIGoYBM5M"


@pytest.mark.parametrize(
    "ref",
    [
        f"https://open.spotify.com/playlist/{PID}?si=abc123",
        f"https://open.spotify.com/intl-es/playlist/{PID}",
        f"spotify:playlist:{PID}",
        PID,
    ],
)
def test_parse_playlist_ref(ref):
    assert parse_playlist_ref(ref) == PID


def test_parse_playlist_ref_liked_and_invalid():
    assert parse_playlist_ref("Liked") == LIKED
    with pytest.raises(ValueError):
        parse_playlist_ref("https://open.spotify.com/album/xyz")


def spotify_item(name, artists, ms=200_000, key="item", kind="track", isrc="ISRC1"):
    return {
        key: {
            "type": kind,
            "name": name,
            "artists": [{"name": a} for a in artists],
            "duration_ms": ms,
            "album": {"name": "Album"},
            "external_ids": {"isrc": isrc},
        }
    }


def test_parse_track_new_and_old_api_shapes():
    for key in ("item", "track"):
        t = parse_track(spotify_item("Song", ["A", "B"], key=key))
        assert t == Track("Song", ("A", "B"), 200, "Album", "ISRC1")


def test_parse_track_skips_episodes_and_removed_tracks():
    assert parse_track(spotify_item("Podcast", ["X"], kind="episode")) is None
    assert parse_track({"track": None}) is None


class FakeSpotify:
    def __init__(self):
        self.pages = {
            "p1": {"items": [spotify_item("One", ["A"])], "next": "p2"},
            "p2": {"items": [spotify_item("Two", ["B"]), {"item": None}], "next": None},
        }

    def playlist_items(self, playlist_id, **kwargs):
        return self.pages["p1"]

    def next(self, page):
        return self.pages[page["next"]]


def test_spotify_source_paginates():
    titles = [t.title for t in SpotifySource(FakeSpotify()).tracks(PID)]
    assert titles == ["One", "Two"]


class FakeYTMusic:
    def __init__(self, catalog):
        self.catalog = catalog  # query -> results
        self.searches = []
        self.created = []
        self.added = []

    def search(self, query, filter=None, limit=20):
        self.searches.append((query, filter))
        return self.catalog.get((query, filter), [])

    def create_playlist(self, title, description, privacy_status="PRIVATE"):
        self.created.append((title, privacy_status))
        return "PLnew"

    def add_playlist_items(self, playlist_id, video_ids, duplicates=False):
        self.added.append((playlist_id, list(video_ids)))
        return {"status": "STATUS_SUCCEEDED"}


def yt_result(video_id, title, artist, seconds, kind="song"):
    return {
        "videoId": video_id,
        "title": title,
        "artists": [{"name": artist}],
        "duration_seconds": seconds,
        "resultType": kind,
    }


def test_find_stops_after_good_isrc_match():
    track = Track("Song", ("Artist",), 200, isrc="ISRC1")
    fake = FakeYTMusic({("ISRC1", "songs"): [yt_result("v1", "Song", "Artist", 200)]})
    result = YTMusicTarget(fake).find(track)
    assert result.status is MatchStatus.MATCHED
    assert result.candidate.video_id == "v1"
    assert fake.searches == [("ISRC1", "songs")]


def test_find_falls_back_to_videos_and_reports_not_found():
    track = Track("Song", ("Artist",), 200)
    fake = FakeYTMusic(
        {("Artist Song", "videos"): [yt_result("v2", "Artist - Song (Official Video)", "Artist VEVO", 205, "video")]}
    )
    target = YTMusicTarget(fake)
    assert target.find(track).candidate.video_id == "v2"
    assert target.find(Track("Nothing", ("Nobody",), 100)).status is MatchStatus.NOT_FOUND


def test_add_videos_dedupes_and_batches():
    fake = FakeYTMusic({})
    ids = [f"v{i}" for i in range(120)] + ["v0"]
    YTMusicTarget(fake).add_videos("PL", ids)
    assert [len(batch) for _, batch in fake.added] == [50, 50, 20]


def test_cli_convert_end_to_end(tmp_path, monkeypatch, capsys):
    auth = tmp_path / "browser.json"
    auth.write_text("{}")
    report_path = tmp_path / "r.csv"

    class Source(SpotifySource):
        def playlist_name(self, playlist_id):
            return "Mi Playlist"

    fake_yt = FakeYTMusic(
        {
            ("ISRC1", "songs"): [yt_result("v1", "One", "A", 200)],
            ("ISRC1", "videos"): [],
        }
    )
    monkeypatch.setattr(SpotifySource, "from_env", classmethod(lambda cls: Source(FakeSpotify())))
    monkeypatch.setattr(YTMusicTarget, "from_auth_file", classmethod(lambda cls, a, delay=0: cls(fake_yt)))

    code = cli.main(["convert", PID, "--auth", str(auth), "--report", str(report_path)])

    assert code == 0
    assert fake_yt.created == [("Mi Playlist", "PRIVATE")]
    assert fake_yt.added == [("PLnew", ["v1"])]
    lines = report_path.read_text(encoding="utf-8-sig").splitlines()
    assert len(lines) == 3  # encabezado + 2 canciones
    assert "no_encontrada" in lines[2]
    out = capsys.readouterr().out
    assert "1 encontradas" in out and "1 no encontradas" in out


def test_cli_dry_run_does_not_touch_ytmusic(tmp_path, monkeypatch):
    auth = tmp_path / "browser.json"
    auth.write_text("{}")
    fake_yt = FakeYTMusic({("ISRC1", "songs"): [yt_result("v1", "One", "A", 200)]})
    monkeypatch.setattr(SpotifySource, "from_env", classmethod(lambda cls: SpotifySource(FakeSpotify())))
    monkeypatch.setattr(YTMusicTarget, "from_auth_file", classmethod(lambda cls, a, delay=0: cls(fake_yt)))
    monkeypatch.setattr(SpotifySource, "playlist_name", lambda self, pid: "X")

    code = cli.main(["convert", PID, "--auth", str(auth), "--dry-run", "--report", str(tmp_path / "r.csv")])

    assert code == 0
    assert fake_yt.created == [] and fake_yt.added == []

import pytest

from playlist_converter.refs import SPOTIFY, YTMUSIC, PlaylistRef, parse_ref, playlist_url
from playlist_converter.spotify_service import SpotifyService, parse_candidate
from playlist_converter.ytmusic_service import YTMusicService, parse_source_track

SP_ID = "37i9dQZF1DXcBWIGoYBM5M"


@pytest.mark.parametrize(
    "text, expected",
    [
        (f"https://open.spotify.com/playlist/{SP_ID}?si=x", PlaylistRef(SPOTIFY, SP_ID)),
        (f"spotify:playlist:{SP_ID}", PlaylistRef(SPOTIFY, SP_ID)),
        ("https://music.youtube.com/playlist?list=PLabc-123_x", PlaylistRef(YTMUSIC, "PLabc-123_x")),
        ("https://www.youtube.com/playlist?list=PLabc&si=zz", PlaylistRef(YTMUSIC, "PLabc")),
        ("https://youtube.com/watch?v=abc&list=OLAK5uy_xyz", PlaylistRef(YTMUSIC, "OLAK5uy_xyz")),
        ("https://music.youtube.com/browse/VLPLqwe", PlaylistRef(YTMUSIC, "PLqwe")),
        ("PLabcdef", PlaylistRef(YTMUSIC, "PLabcdef")),
        ("VLPLabcdef", PlaylistRef(YTMUSIC, "PLabcdef")),
        ("liked", PlaylistRef(SPOTIFY, "liked")),
    ],
)
def test_parse_ref(text, expected):
    assert parse_ref(text) == expected


def test_parse_ref_liked_for_ytmusic_and_errors():
    assert parse_ref("Me gusta", liked_service=YTMUSIC) == PlaylistRef(YTMUSIC, "LM")
    with pytest.raises(ValueError):
        parse_ref("https://open.spotify.com/album/xyz")


def test_playlist_url():
    assert playlist_url(PlaylistRef(SPOTIFY, SP_ID)).endswith(f"/playlist/{SP_ID}")
    assert playlist_url(PlaylistRef(YTMUSIC, "PLx")) == "https://music.youtube.com/playlist?list=PLx"


# ---------------------------------------------------------- YouTube Music como origen
def yt_item(title, artists, video_type="MUSIC_VIDEO_TYPE_ATV", video_id="v1", seconds=200):
    return {
        "videoId": video_id,
        "title": title,
        "artists": [{"name": a} for a in artists],
        "album": {"name": "Álbum"},
        "duration_seconds": seconds,
        "videoType": video_type,
        "setVideoId": "set-" + video_id,
    }


def test_official_song_is_read_as_is():
    t = parse_source_track(yt_item("Bohemian Rhapsody", ["Queen"]))
    assert (t.title, t.artists, t.source_id, t.album) == ("Bohemian Rhapsody", ("Queen",), "v1", "Álbum")


def test_video_title_is_split_into_artist_and_title():
    t = parse_source_track(
        yt_item("KAROL G, Nicki Minaj - Tusa (Official Video)", ["KarolGVEVO"], "MUSIC_VIDEO_TYPE_OMV")
    )
    assert t.artists == ("KAROL G", "Nicki Minaj")
    assert t.title == "Tusa (Official Video)"  # el ruido se limpia al comparar


def test_uploader_channel_suffixes_are_removed():
    t = parse_source_track(yt_item("Crimen", ["Gustavo Cerati - Topic"]))
    assert t.artists == ("Gustavo Cerati",)


def test_video_without_dash_keeps_channel_as_artist():
    t = parse_source_track(yt_item("Crimen", ["Gustavo Cerati"], "MUSIC_VIDEO_TYPE_UGC"))
    assert (t.title, t.artists) == ("Crimen", ("Gustavo Cerati",))


class FakeYTClient:
    def __init__(self):
        self.removed = None
        self.calls = 0

    def get_playlist(self, pid, limit=None):
        self.calls += 1
        return {
            "title": "Mi lista YT",
            "tracks": [yt_item("Uno", ["A"], video_id="v1"), yt_item("Dos", ["B"], video_id="v2")],
        }

    def remove_playlist_items(self, pid, videos):
        self.removed = videos
        return "STATUS_SUCCEEDED"


def test_ytmusic_service_reads_and_removes():
    client = FakeYTClient()
    service = YTMusicService(client)
    assert service.playlist_name("PLx") == "Mi lista YT"
    assert [t.title for t in service.tracks("PLx")] == ["Uno", "Dos"]
    assert client.calls == 1  # el nombre y las canciones usan la misma lectura
    assert service.playlist_name("LM") == "Me gusta (YouTube Music)"
    assert service.playlist_item_ids("PLx") == ["v1", "v2"]
    service.remove_items("PLx", ["v2"])
    assert [v["setVideoId"] for v in client.removed] == ["set-v2"]


# ---------------------------------------------------------- Spotify como destino
def sp_track(track_id, name, artist, seconds):
    return {
        "id": track_id,
        "name": name,
        "artists": [{"name": artist}],
        "duration_ms": seconds * 1000,
        "external_urls": {"spotify": f"https://open.spotify.com/track/{track_id}"},
    }


class FakeSpotifyClient:
    def __init__(self, results):
        self.results = results  # consulta → lista de canciones
        self.queries = []
        self.created = []
        self.added = []
        self.removed = []

    def search(self, q, limit=10, type="track", market=None):
        self.queries.append(q)
        if q == "boom":
            err = Exception("bad request")
            err.http_status = 400
            raise err
        return {"tracks": {"items": self.results.get(q, [])}}

    def current_user_playlist_create(self, name, public=True, collaborative=False, description=""):
        self.created.append((name, public, description))
        return {"id": "SPnew"}

    def playlist_add_items(self, pid, items):
        self.added.append(list(items))

    def playlist_remove_all_occurrences_of_items(self, pid, items):
        self.removed.append(list(items))


def test_parse_spotify_candidate():
    c = parse_candidate(sp_track("t1", "Tusa", "KAROL G", 200))
    assert (c.id, c.title, c.artists, c.duration_seconds) == ("t1", "Tusa", ("KAROL G",), 200)
    assert c.url.endswith("/track/t1")


def test_spotify_find_uses_field_search_and_cleans_video_title():
    from playlist_converter.models import MatchStatus, Track

    wanted = Track("Tusa (Official Video)", ("KAROL G", "Nicki Minaj"), 201)
    client = FakeSpotifyClient({'track:"Tusa" artist:"KAROL G"': [sp_track("t1", "Tusa", "KAROL G", 200)]})
    result = SpotifyService(client).find(wanted)
    assert result.status is MatchStatus.MATCHED
    assert result.candidate.id == "t1"
    assert client.queries == ['track:"Tusa" artist:"KAROL G"']


def test_spotify_find_falls_back_and_survives_bad_queries(monkeypatch):
    from playlist_converter.models import MatchStatus, Track

    client = FakeSpotifyClient({"Queen Bohemian Rhapsody": [sp_track("t9", "Bohemian Rhapsody", "Queen", 354)]})
    service = SpotifyService(client)
    result = service.find(Track("Bohemian Rhapsody", ("Queen",), 355))
    assert result.candidate.id == "t9"
    assert len(client.queries) == 2

    client.results = {}
    assert service.find(Track("Nada", ("Nadie",), 100)).status is MatchStatus.NOT_FOUND
    assert service._search("boom") == []


def test_spotify_create_add_remove():
    client = FakeSpotifyClient({})
    service = SpotifyService(client)
    assert service.create_playlist("Mi lista", "desc", "UNLISTED") == "SPnew"
    assert client.created == [("Mi lista", False, "desc")]  # sin "no listada": queda privada
    service.create_playlist("Pública", "d", "PUBLIC")
    assert client.created[-1][1] is True
    service.add_items("SPnew", [f"t{i}" for i in range(150)] + ["t0"])
    assert [len(b) for b in client.added] == [100, 50]
    service.remove_items("SPnew", ["t1", "t2"])
    assert client.removed == [["t1", "t2"]]


def test_spotify_find_handles_title_artist_reversed():
    from playlist_converter.models import MatchStatus, Track

    reversed_video = Track("Don Omar & Daddy Yankee", ("Hasta Abajo Remix",), 243)
    client = FakeSpotifyClient(
        {"Don Omar Hasta Abajo Remix": [sp_track("t5", "Hasta Abajo - Remix", "Don Omar", 241)]}
    )
    result = SpotifyService(client).find(reversed_video)
    assert result.status is MatchStatus.MATCHED and result.candidate.id == "t5"
    assert result.track is reversed_video  # se recuerda con la canción original


def test_split_artists():
    from playlist_converter.matcher import split_artists

    assert split_artists("KAROL G, Nicki Minaj") == ("KAROL G", "Nicki Minaj")
    assert split_artists("Don Omar & Daddy Yankee") == ("Don Omar", "Daddy Yankee")
    assert split_artists("Bad Bunny x Jhay Cortez") == ("Bad Bunny", "Jhay Cortez")
    assert split_artists("Queen") == ("Queen",)

"""Lectura de playlists (y canciones guardadas) desde la API de Spotify."""

from __future__ import annotations

import re
from typing import Any, Iterator

from .models import Track

LIKED = "liked"
SCOPES = "playlist-read-private playlist-read-collaborative user-library-read"
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"

_ID_RE = re.compile(r"^[A-Za-z0-9]{22}$")
_URL_RE = re.compile(r"open\.spotify\.com/(?:intl-[a-z-]+/)?playlist/([A-Za-z0-9]{22})")
_URI_RE = re.compile(r"^spotify:playlist:([A-Za-z0-9]{22})$")


def parse_playlist_ref(ref: str) -> str:
    """Devuelve el ID de la playlist, o LIKED para las canciones guardadas.

    Acepta una URL de open.spotify.com, una URI spotify:playlist:..., un ID
    o la palabra 'liked'.
    """
    ref = ref.strip()
    if ref.lower() == LIKED:
        return LIKED
    for pattern in (_URL_RE, _URI_RE):
        m = pattern.search(ref)
        if m:
            return m.group(1)
    if _ID_RE.match(ref):
        return ref
    raise ValueError(f"No reconozco '{ref}' como playlist de Spotify.")


def parse_track(entry: dict[str, Any]) -> Track | None:
    """Convierte un elemento de la API en Track. Ignora podcasts y vacíos."""
    # La API nueva usa "item"; la antigua usaba "track".
    data = entry.get("item") or entry.get("track")
    if not data or data.get("type", "track") != "track":
        return None
    title = (data.get("name") or "").strip()
    if not title:
        return None
    duration_ms = data.get("duration_ms")
    return Track(
        title=title,
        artists=tuple(a["name"] for a in data.get("artists") or [] if a.get("name")),
        duration_seconds=round(duration_ms / 1000) if duration_ms else None,
        album=(data.get("album") or {}).get("name"),
        isrc=(data.get("external_ids") or {}).get("isrc"),
    )


class SpotifySource:
    def __init__(self, client: Any):
        self.client = client

    @classmethod
    def from_env(cls, cache_path: str | None = None) -> "SpotifySource":
        """Crea el cliente usando SPOTIPY_CLIENT_ID / SPOTIPY_CLIENT_SECRET."""
        import os

        from .accounts import app_dir

        if cache_path is None:
            cache_path = str(app_dir() / ".spotify_cache")
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth

        auth = SpotifyOAuth(
            scope=SCOPES,
            redirect_uri=os.environ.get("SPOTIPY_REDIRECT_URI", DEFAULT_REDIRECT_URI),
            cache_path=cache_path,
            open_browser=True,
        )
        return cls(spotipy.Spotify(auth_manager=auth, retries=5))

    def playlist_name(self, playlist_id: str) -> str:
        if playlist_id == LIKED:
            return "Canciones que me gustan"
        return self.client.playlist(playlist_id, fields="name")["name"]

    def tracks(self, playlist_id: str) -> Iterator[Track]:
        if playlist_id == LIKED:
            page = self.client.current_user_saved_tracks(limit=50)
        else:
            page = self.client.playlist_items(playlist_id, limit=100, additional_types=("track",))
        while page:
            for entry in page.get("items") or []:
                track = parse_track(entry)
                if track:
                    yield track
            page = self.client.next(page) if page.get("next") else None

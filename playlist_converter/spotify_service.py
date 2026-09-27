"""Spotify como origen (leer playlists) y como destino (buscar canciones y crear playlists)."""

from __future__ import annotations

from typing import Any, Iterator

from . import matcher
from .models import Candidate, MatchResult, MatchStatus, Track
from .refs import SPOTIFY, SPOTIFY_LIKED, parse_ref

LIKED = SPOTIFY_LIKED
SCOPES = (
    "playlist-read-private playlist-read-collaborative user-library-read "
    "playlist-modify-private playlist-modify-public"
)
DEFAULT_REDIRECT_URI = "http://127.0.0.1:8888/callback"
BATCH_SIZE = 100  # máximo que acepta la API por petición


def parse_playlist_ref(ref: str) -> str:
    """Devuelve el ID de una playlist de Spotify, o LIKED para las canciones guardadas."""
    parsed = parse_ref(ref, liked_service=SPOTIFY)
    if parsed.service != SPOTIFY:
        raise ValueError(f"'{ref}' no es una playlist de Spotify.")
    return parsed.id


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
        source_id=data.get("id"),
    )


def parse_candidate(data: dict[str, Any]) -> Candidate | None:
    if not data or not data.get("id"):
        return None
    duration_ms = data.get("duration_ms")
    return Candidate(
        id=data["id"],
        title=data.get("name") or "",
        artists=tuple(a["name"] for a in data.get("artists") or [] if a.get("name")),
        duration_seconds=round(duration_ms / 1000) if duration_ms else None,
        result_type="song",
        url=(data.get("external_urls") or {}).get("spotify") or f"https://open.spotify.com/track/{data['id']}",
    )


class SpotifyService:
    service = SPOTIFY

    def __init__(self, client: Any):
        self.client = client

    @classmethod
    def from_env(cls, cache_path: str | None = None) -> "SpotifyService":
        """Crea el cliente usando SPOTIPY_CLIENT_ID / SPOTIPY_CLIENT_SECRET."""
        import os

        import spotipy
        from spotipy.oauth2 import SpotifyOAuth

        from .accounts import app_dir

        if cache_path is None:
            cache_path = str(app_dir() / ".spotify_cache")
        auth = SpotifyOAuth(
            scope=SCOPES,
            redirect_uri=os.environ.get("SPOTIPY_REDIRECT_URI", DEFAULT_REDIRECT_URI),
            cache_path=cache_path,
            open_browser=True,
        )
        return cls(spotipy.Spotify(auth_manager=auth, retries=5))

    # ---------------------------------------------------------------- origen
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

    # --------------------------------------------------------------- destino
    def _search(self, query: str, limit: int = 5) -> list[Candidate]:
        try:
            response = self.client.search(query, limit=limit, type="track", market="from_token")
        except Exception as exc:  # consultas con caracteres raros pueden dar 400
            if getattr(exc, "http_status", None) == 400:
                return []
            raise
        items = ((response or {}).get("tracks") or {}).get("items") or []
        candidates = (parse_candidate(item) for item in items)
        return [c for c in candidates if c]

    def find(self, track: Track) -> MatchResult:
        title = matcher.clean_title(track.title)
        artist = track.primary_artist
        strategies = []
        if track.isrc:
            strategies.append(f"isrc:{track.isrc}")
        if artist:
            strategies.append(f'track:"{title}" artist:"{artist}"')
        strategies.append(f"{artist} {title}".strip())

        best: Candidate | None = None
        best_score = 0.0
        for query in strategies:
            candidate, s = matcher.best_candidate(track, self._search(query))
            if s > best_score:
                best, best_score = candidate, s
            if best_score >= matcher.MATCH_THRESHOLD:
                break

        # Algunos videos de YouTube se titulan "Canción - Artista": probar al revés.
        alternative = matcher.swapped(track) if best_score < matcher.MATCH_THRESHOLD else None
        if alternative:
            query = f"{alternative.primary_artist} {alternative.title}".strip()
            candidate, s = matcher.best_candidate(alternative, self._search(query))
            if s > best_score:
                best, best_score = candidate, s
        return _result(track, best, best_score)

    def create_playlist(self, title: str, description: str, privacy: str) -> str:
        # Spotify no tiene "no listada": solo pública o privada.
        playlist = self.client.current_user_playlist_create(
            title, public=privacy == "PUBLIC", description=description
        )
        return playlist["id"]

    def add_items(self, playlist_id: str, item_ids: list[str]) -> None:
        unique = list(dict.fromkeys(item_ids))
        for start in range(0, len(unique), BATCH_SIZE):
            self.client.playlist_add_items(playlist_id, unique[start : start + BATCH_SIZE])

    def playlist_item_ids(self, playlist_id: str) -> list[str]:
        return [t.source_id for t in self.tracks(playlist_id) if t.source_id]

    def remove_items(self, playlist_id: str, item_ids: list[str]) -> None:
        unique = list(dict.fromkeys(item_ids))
        for start in range(0, len(unique), BATCH_SIZE):
            self.client.playlist_remove_all_occurrences_of_items(
                playlist_id, unique[start : start + BATCH_SIZE]
            )


def _result(track: Track, best: Candidate | None, best_score: float) -> MatchResult:
    if best is None or best_score < matcher.LOW_CONFIDENCE_THRESHOLD:
        return MatchResult(track, MatchStatus.NOT_FOUND, best, best_score)
    status = MatchStatus.MATCHED if best_score >= matcher.MATCH_THRESHOLD else MatchStatus.LOW_CONFIDENCE
    return MatchResult(track, status, best, best_score)


# Compatibilidad con versiones anteriores.
SpotifySource = SpotifyService

"""YouTube Music como destino (buscar y crear playlists) y como origen (leer playlists)."""

from __future__ import annotations

import re
import time
from typing import Any, Iterator

from . import matcher
from .models import Candidate, MatchResult, MatchStatus, Track
from .refs import YTMUSIC, YTMUSIC_LIKED

ADD_BATCH_SIZE = 50
SONG_VIDEO_TYPE = "MUSIC_VIDEO_TYPE_ATV"  # audio oficial: título y artista vienen limpios

_TITLE_SPLIT_RE = re.compile(r"\s+[-–—]\s+")
_CHANNEL_SUFFIX_RE = re.compile(r"\s*(?:-\s*topic|vevo|official|oficial)\s*$", re.IGNORECASE)


def parse_candidate(result: dict[str, Any]) -> Candidate | None:
    video_id = result.get("videoId")
    if not video_id:
        return None
    return Candidate(
        id=video_id,
        title=result.get("title") or "",
        artists=tuple(a["name"] for a in result.get("artists") or [] if a.get("name")),
        duration_seconds=result.get("duration_seconds"),
        result_type="song" if result.get("resultType") == "song" else "video",
        url=f"https://music.youtube.com/watch?v={video_id}",
    )


def parse_source_track(item: dict[str, Any]) -> Track | None:
    """Convierte una canción de una playlist de YouTube Music en Track.

    En videos (no canciones oficiales) el título suele ser "Artista - Canción" y el
    "artista" es el canal que lo subió, así que se separan.
    """
    title = (item.get("title") or "").strip()
    if not title:
        return None
    artists = [
        _CHANNEL_SUFFIX_RE.sub("", a["name"]).strip()
        for a in item.get("artists") or []
        if a.get("name")
    ]
    artists = [a for a in artists if a]
    if item.get("videoType") != SONG_VIDEO_TYPE:
        parts = _TITLE_SPLIT_RE.split(title, maxsplit=1)
        if len(parts) == 2 and parts[0] and parts[1]:
            left, right = parts
            artists = list(matcher.split_artists(left)) or artists
            title = right
    return Track(
        title=title,
        artists=tuple(artists),
        duration_seconds=item.get("duration_seconds"),
        album=(item.get("album") or {}).get("name"),
        source_id=item.get("videoId"),
    )


class YTMusicService:
    service = YTMUSIC

    def __init__(self, client: Any, delay: float = 0.0):
        self.client = client
        self.delay = delay
        self._playlists: dict[str, dict] = {}

    @classmethod
    def from_auth_file(cls, auth_file: str | None, delay: float = 0.0) -> "YTMusicService":
        """Con auth_file=None se usa sin sesión (solo sirve para leer playlists públicas)."""
        from ytmusicapi import YTMusic

        return cls(YTMusic(auth_file) if auth_file else YTMusic(), delay=delay)

    # ---------------------------------------------------------------- origen
    def _playlist(self, playlist_id: str, fresh: bool = False) -> dict:
        if fresh or playlist_id not in self._playlists:
            self._playlists[playlist_id] = self.client.get_playlist(playlist_id, limit=None)
        return self._playlists[playlist_id]

    def playlist_name(self, playlist_id: str) -> str:
        if playlist_id == YTMUSIC_LIKED:
            return "Me gusta (YouTube Music)"
        return self._playlist(playlist_id).get("title") or "Playlist de YouTube Music"

    def tracks(self, playlist_id: str) -> Iterator[Track]:
        for item in self._playlist(playlist_id).get("tracks") or []:
            track = parse_source_track(item)
            if track:
                yield track

    # --------------------------------------------------------------- destino
    def _search(self, query: str, filter: str, limit: int = 5) -> list[Candidate]:
        if self.delay:
            time.sleep(self.delay)
        results = self.client.search(query, filter=filter, limit=limit)
        candidates = (parse_candidate(r) for r in results[:limit])
        return [c for c in candidates if c]

    def find(self, track: Track) -> MatchResult:
        """Busca la canción probando varias estrategias, de la más precisa a la menos."""
        strategies = []
        if track.isrc:
            strategies.append((track.isrc, "songs"))
        query = matcher.build_query(track)
        strategies += [(query, "songs"), (query, "videos")]

        best: Candidate | None = None
        best_score = 0.0
        for q, search_filter in strategies:
            candidate, s = matcher.best_candidate(track, self._search(q, search_filter))
            if s > best_score:
                best, best_score = candidate, s
            if best_score >= matcher.MATCH_THRESHOLD:
                break

        if best is None or best_score < matcher.LOW_CONFIDENCE_THRESHOLD:
            return MatchResult(track, MatchStatus.NOT_FOUND, best, best_score)
        status = (
            MatchStatus.MATCHED
            if best_score >= matcher.MATCH_THRESHOLD
            else MatchStatus.LOW_CONFIDENCE
        )
        return MatchResult(track, status, best, best_score)

    def create_playlist(self, title: str, description: str, privacy: str) -> str:
        playlist_id = self.client.create_playlist(title, description, privacy_status=privacy)
        if not isinstance(playlist_id, str):
            raise RuntimeError(f"YouTube Music no pudo crear la playlist: {playlist_id}")
        return playlist_id

    def add_items(self, playlist_id: str, item_ids: list[str]) -> None:
        # Quitamos duplicados manteniendo el orden: YouTube Music rechaza
        # el lote completo si trae repetidos.
        unique = list(dict.fromkeys(item_ids))
        for start in range(0, len(unique), ADD_BATCH_SIZE):
            batch = unique[start : start + ADD_BATCH_SIZE]
            response = self.client.add_playlist_items(playlist_id, batch, duplicates=True)
            status = response.get("status", "") if isinstance(response, dict) else str(response)
            if "SUCCEEDED" not in status:
                raise RuntimeError(f"Error agregando canciones a la playlist: {response}")
        self._playlists.pop(playlist_id, None)

    def playlist_item_ids(self, playlist_id: str) -> list[str]:
        tracks = self._playlist(playlist_id, fresh=True).get("tracks") or []
        return [t["videoId"] for t in tracks if t.get("videoId")]

    def remove_items(self, playlist_id: str, item_ids: list[str]) -> None:
        wanted = set(item_ids)
        tracks = self._playlist(playlist_id, fresh=True).get("tracks") or []
        videos = [t for t in tracks if t.get("videoId") in wanted and t.get("setVideoId")]
        if videos:
            self.client.remove_playlist_items(playlist_id, videos)
        self._playlists.pop(playlist_id, None)

    # Nombre anterior del método (antes solo existía esta dirección).
    add_videos = add_items


# Compatibilidad con versiones anteriores.
YTMusicTarget = YTMusicService

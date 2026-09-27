"""Búsqueda de canciones y creación de playlists en YouTube Music."""

from __future__ import annotations

import time
from typing import Any

from . import matcher
from .models import Candidate, MatchResult, MatchStatus, Track

ADD_BATCH_SIZE = 50


def parse_candidate(result: dict[str, Any]) -> Candidate | None:
    video_id = result.get("videoId")
    if not video_id:
        return None
    return Candidate(
        video_id=video_id,
        title=result.get("title") or "",
        artists=tuple(a["name"] for a in result.get("artists") or [] if a.get("name")),
        duration_seconds=result.get("duration_seconds"),
        result_type="song" if result.get("resultType") == "song" else "video",
    )


class YTMusicTarget:
    def __init__(self, client: Any, delay: float = 0.0):
        self.client = client
        self.delay = delay

    @classmethod
    def from_auth_file(cls, auth_file: str, delay: float = 0.0) -> "YTMusicTarget":
        from ytmusicapi import YTMusic

        return cls(YTMusic(auth_file), delay=delay)

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

    def add_videos(self, playlist_id: str, video_ids: list[str]) -> None:
        # Quitamos duplicados manteniendo el orden: YouTube Music rechaza
        # el lote completo si trae repetidos.
        unique = list(dict.fromkeys(video_ids))
        for start in range(0, len(unique), ADD_BATCH_SIZE):
            batch = unique[start : start + ADD_BATCH_SIZE]
            response = self.client.add_playlist_items(playlist_id, batch, duplicates=True)
            status = response.get("status", "") if isinstance(response, dict) else str(response)
            if "SUCCEEDED" not in status:
                raise RuntimeError(f"Error agregando canciones a la playlist: {response}")

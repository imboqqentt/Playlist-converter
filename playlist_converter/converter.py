"""El proceso de conversión, compartido por la línea de comandos y la ventana."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from .models import MatchResult, MatchStatus

DESCRIPTION = "Convertida desde Spotify con Playlist Converter"


@dataclass
class ConvertOptions:
    name: str | None = None
    privacy: str = "PRIVATE"
    strict: bool = False
    dry_run: bool = False
    limit: int | None = None
    append_to: str | None = None


@dataclass
class ConvertOutcome:
    playlist_name: str
    results: list[MatchResult] = field(default_factory=list)
    playlist_id: str | None = None
    added: int = 0
    cancelled: bool = False

    @property
    def playlist_url(self) -> str | None:
        if not self.playlist_id:
            return None
        return f"https://music.youtube.com/playlist?list={self.playlist_id}"


class Cancelled(Exception):
    pass


def video_ids_to_add(results: list[MatchResult], strict: bool) -> list[str]:
    allowed = {MatchStatus.MATCHED} if strict else {MatchStatus.MATCHED, MatchStatus.LOW_CONFIDENCE}
    return [r.candidate.video_id for r in results if r.status in allowed and r.candidate]


def convert(
    spotify,
    ytmusic,
    playlist_id: str,
    options: ConvertOptions,
    on_start: Callable[[str, int], None] = lambda name, total: None,
    on_result: Callable[[int, int, MatchResult], None] = lambda i, total, result: None,
    on_status: Callable[[str], None] = lambda message: None,
    cancel: threading.Event | None = None,
) -> ConvertOutcome:
    """Lee la playlist, busca cada canción y (salvo dry_run) crea la playlist.

    Si `cancel` se activa, se detiene antes de modificar YouTube Music.
    """
    name = options.name or spotify.playlist_name(playlist_id)
    on_status(f"Leyendo '{name}' desde Spotify...")
    tracks = list(spotify.tracks(playlist_id))
    if options.limit:
        tracks = tracks[: options.limit]

    outcome = ConvertOutcome(playlist_name=name)
    on_start(name, len(tracks))
    for i, track in enumerate(tracks, start=1):
        if cancel is not None and cancel.is_set():
            outcome.cancelled = True
            return outcome
        result = ytmusic.find(track)
        outcome.results.append(result)
        on_result(i, len(tracks), result)

    video_ids = video_ids_to_add(outcome.results, options.strict)
    if options.dry_run or not video_ids:
        return outcome

    on_status("Creando la playlist en YouTube Music...")
    if options.append_to:
        outcome.playlist_id = options.append_to
    else:
        outcome.playlist_id = ytmusic.create_playlist(name, DESCRIPTION, options.privacy)
    ytmusic.add_videos(outcome.playlist_id, video_ids)
    outcome.added = len(set(video_ids))
    return outcome

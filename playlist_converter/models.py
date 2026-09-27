"""Estructuras de datos compartidas por todo el conversor."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class Track:
    """Una canción leída desde Spotify."""

    title: str
    artists: tuple[str, ...]
    duration_seconds: int | None = None
    album: str | None = None
    isrc: str | None = None

    @property
    def primary_artist(self) -> str:
        return self.artists[0] if self.artists else ""

    def display(self) -> str:
        artists = ", ".join(self.artists) or "?"
        return f"{artists} - {self.title}"


@dataclass(frozen=True)
class Candidate:
    """Un resultado de búsqueda de YouTube Music."""

    video_id: str
    title: str
    artists: tuple[str, ...]
    duration_seconds: int | None = None
    result_type: str = "song"  # "song" (audio oficial) o "video"

    @property
    def url(self) -> str:
        return f"https://music.youtube.com/watch?v={self.video_id}"


class MatchStatus(str, Enum):
    MATCHED = "encontrada"
    LOW_CONFIDENCE = "dudosa"
    NOT_FOUND = "no_encontrada"


@dataclass
class MatchResult:
    track: Track
    status: MatchStatus
    candidate: Candidate | None = None
    score: float = 0.0
    notes: list[str] = field(default_factory=list)

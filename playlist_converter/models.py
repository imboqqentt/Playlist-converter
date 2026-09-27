"""Estructuras de datos compartidas por todo el conversor."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class Track:
    """Una canción leída desde la playlist de origen (Spotify o YouTube Music)."""

    title: str
    artists: tuple[str, ...]
    duration_seconds: int | None = None
    album: str | None = None
    isrc: str | None = None
    source_id: str | None = None  # ID de la canción en el servicio de origen

    @property
    def key(self) -> str:
        """Identificador estable para recordar qué canciones ya se sincronizaron."""
        return self.source_id or f"~{self.display().lower()}"

    @property
    def primary_artist(self) -> str:
        return self.artists[0] if self.artists else ""

    def display(self) -> str:
        artists = ", ".join(self.artists) or "?"
        return f"{artists} - {self.title}"


@dataclass(frozen=True)
class Candidate:
    """Un resultado de búsqueda en el servicio de destino."""

    id: str  # videoId de YouTube Music o ID de canción de Spotify
    title: str
    artists: tuple[str, ...]
    duration_seconds: int | None = None
    result_type: str = "song"  # "song" (audio oficial) o "video"
    url: str = ""


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

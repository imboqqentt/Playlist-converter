"""Reporte CSV con el resultado de cada canción."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

from .models import MatchResult, MatchStatus

COLUMNS = [
    "n",
    "estado",
    "puntaje",
    "origen_artistas",
    "origen_titulo",
    "origen_duracion",
    "destino_titulo",
    "destino_artistas",
    "destino_duracion",
    "destino_url",
]


def write_csv(results: list[MatchResult], path: Path) -> None:
    # utf-8-sig para que Excel muestre bien los acentos.
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        for n, r in enumerate(results, start=1):
            c = r.candidate
            writer.writerow(
                [
                    n,
                    r.status.value,
                    f"{r.score:.2f}",
                    ", ".join(r.track.artists),
                    r.track.title,
                    format_duration(r.track.duration_seconds),
                    c.title if c else "",
                    ", ".join(c.artists) if c else "",
                    format_duration(c.duration_seconds) if c else "",
                    c.url if c else "",
                ]
            )


def summary(results: list[MatchResult]) -> str:
    counts = Counter(r.status for r in results)
    return (
        f"{len(results)} canciones: "
        f"{counts[MatchStatus.MATCHED]} encontradas, "
        f"{counts[MatchStatus.LOW_CONFIDENCE]} dudosas, "
        f"{counts[MatchStatus.NOT_FOUND]} no encontradas"
    )


def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return ""
    return f"{seconds // 60}:{seconds % 60:02d}"

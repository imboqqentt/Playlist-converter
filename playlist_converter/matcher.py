"""Lógica para decidir qué resultado de YouTube Music corresponde a una canción.

Todo lo de este módulo es puro (sin red), para poder probarlo fácilmente.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import Candidate, Track

# Umbrales de puntaje (0 a 1).
MATCH_THRESHOLD = 0.75
LOW_CONFIDENCE_THRESHOLD = 0.5

# Palabras que indican una versión distinta de la original. Solo penalizan
# si NO aparecen también en el título/álbum de Spotify.
# Otra interpretación o un audio que no es la canción: penalización fuerte.
NOT_ORIGINAL_KEYWORDS = (
    "cover",
    "karaoke",
    "instrumental",
    "tutorial",
    "reaction",
    "nightcore",
    "8d",
    "sped up",
    "slowed",
)
# Otra versión del mismo artista: penalización moderada.
VARIANT_KEYWORDS = (
    "live",
    "en vivo",
    "ao vivo",
    "en directo",
    "remix",
    "acoustic",
    "acustico",
    "acustica",
    "unplugged",
    "desenchufado",
    "demo",
    "reverb",
)

_FEAT_RE = re.compile(r"[\(\[]\s*(feat|ft|with|con)\.?\s[^\)\]]*[\)\]]", re.IGNORECASE)
_SUFFIX_RE = re.compile(
    r"\s+-\s+(\d{4}\s+)?(remaster(ed)?|mono|stereo|single|radio edit|album version)\b.*$",
    re.IGNORECASE,
)
_REMASTER_PAREN_RE = re.compile(r"[\(\[][^\)\]]*remaster[^\)\]]*[\)\]]", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def normalize(text: str) -> str:
    """Minúsculas, sin acentos ni puntuación, espacios colapsados."""
    text = strip_accents(text.lower()).replace("&", " and ")
    return _NON_ALNUM_RE.sub(" ", text).strip()


def clean_title(title: str) -> str:
    """Quita adornos típicos de Spotify: '(feat. X)', '- Remastered 2011', etc."""
    title = _FEAT_RE.sub("", title)
    title = _REMASTER_PAREN_RE.sub("", title)
    title = _SUFFIX_RE.sub("", title)
    return title.strip()


def build_query(track: Track) -> str:
    return f"{track.primary_artist} {clean_title(track.title)}".strip()


def title_score(track: Track, candidate: Candidate) -> float:
    wanted = normalize(clean_title(track.title))
    got = normalize(clean_title(candidate.title))
    if not wanted or not got:
        return 0.0
    ratio = SequenceMatcher(None, wanted, got).ratio()
    # Los videos suelen llamarse "Artista - Título (Official Video)".
    if _contains_words(got, wanted):
        ratio = max(ratio, 0.9)
    return ratio


def artist_score(track: Track, candidate: Candidate) -> float:
    if not track.artists:
        return 0.5
    # Que el artista sea el autor del resultado (canal "Queen - Topic",
    # "Queen Official") vale más que solo aparecer en el título, como pasa
    # en los videos subidos por terceros ("Queen - X (Lyrics)").
    channel = normalize(" ".join(candidate.artists))
    title = normalize(candidate.title)
    primary = normalize(track.primary_artist)
    others = [normalize(a) for a in track.artists[1:] if a]
    if primary and _contains_words(channel, primary):
        return 1.0
    if primary and _contains_words(title, primary):
        return 0.7
    if any(_contains_words(channel, a) or _contains_words(title, a) for a in others):
        return 0.6
    return 0.0


def duration_score(track: Track, candidate: Candidate) -> float:
    if track.duration_seconds is None or candidate.duration_seconds is None:
        return 0.5
    diff = abs(track.duration_seconds - candidate.duration_seconds)
    if diff <= 3:
        return 1.0
    if diff <= 10:
        return 0.8
    if diff <= 20:
        return 0.5
    if diff <= 40:
        return 0.2
    return 0.0


def duration_penalty(track: Track, candidate: Candidate) -> float:
    """Una diferencia grande de duración casi siempre es otra versión."""
    if track.duration_seconds is None or candidate.duration_seconds is None:
        return 0.0
    return 0.2 if abs(track.duration_seconds - candidate.duration_seconds) > 40 else 0.0


def variant_penalty(track: Track, candidate: Candidate) -> float:
    original = f" {normalize(track.title)} {normalize(track.album or '')} "
    found = f" {normalize(candidate.title)} "
    penalty = 0.0
    for keywords, weight in ((NOT_ORIGINAL_KEYWORDS, 0.5), (VARIANT_KEYWORDS, 0.3)):
        for keyword in keywords:
            needle = f" {keyword} "
            if needle in found and needle not in original:
                penalty += weight
    return min(penalty, 0.6)


def score(track: Track, candidate: Candidate) -> float:
    total = (
        0.45 * title_score(track, candidate)
        + 0.30 * artist_score(track, candidate)
        + 0.25 * duration_score(track, candidate)
        - variant_penalty(track, candidate)
        - duration_penalty(track, candidate)
    )
    if candidate.result_type == "song":
        total += 0.05  # preferimos el audio oficial ("Topic") por sobre videos
    return max(0.0, min(1.0, total))


def best_candidate(
    track: Track, candidates: list[Candidate]
) -> tuple[Candidate | None, float]:
    best: Candidate | None = None
    best_score = 0.0
    for candidate in candidates:
        s = score(track, candidate)
        if s > best_score:
            best, best_score = candidate, s
    return best, best_score


def _contains_words(haystack: str, needle: str) -> bool:
    return f" {needle} " in f" {haystack} "

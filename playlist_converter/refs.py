"""Reconoce links de playlists de Spotify y de YouTube Music."""

from __future__ import annotations

import re
from dataclasses import dataclass

SPOTIFY = "spotify"
YTMUSIC = "ytmusic"
SERVICE_NAMES = {SPOTIFY: "Spotify", YTMUSIC: "YouTube Music"}

SPOTIFY_LIKED = "liked"
YTMUSIC_LIKED = "LM"
LIKED_WORDS = {"liked", "me gusta", "megusta", "favoritas"}

_SPOTIFY_URL = re.compile(r"open\.spotify\.com/(?:intl-[a-z-]+/)?playlist/([A-Za-z0-9]{22})")
_SPOTIFY_URI = re.compile(r"^spotify:playlist:([A-Za-z0-9]{22})$")
_SPOTIFY_ID = re.compile(r"^[A-Za-z0-9]{22}$")
_YT_LIST_PARAM = re.compile(r"(?:youtube\.com|youtu\.be)/.*[?&]list=([\w-]+)")
_YT_BROWSE = re.compile(r"music\.youtube\.com/browse/VL([\w-]+)")
_YT_ID = re.compile(r"^(?:PL|OLAK5uy_|RDCLAK|UU|FL|LM$)[\w-]*$")


@dataclass(frozen=True)
class PlaylistRef:
    service: str
    id: str

    @property
    def is_liked(self) -> bool:
        return self.id in (SPOTIFY_LIKED, YTMUSIC_LIKED)


def other_service(service: str) -> str:
    return YTMUSIC if service == SPOTIFY else SPOTIFY


def liked_ref(service: str) -> PlaylistRef:
    return PlaylistRef(service, SPOTIFY_LIKED if service == SPOTIFY else YTMUSIC_LIKED)


def parse_ref(text: str, liked_service: str = SPOTIFY) -> PlaylistRef:
    """Detecta el servicio y el ID a partir de un link, URI o ID.

    'liked' se interpreta como las canciones guardadas de `liked_service`.
    """
    text = text.strip()
    if text.lower() in LIKED_WORDS:
        return liked_ref(liked_service)
    for pattern in (_SPOTIFY_URL, _SPOTIFY_URI):
        m = pattern.search(text)
        if m:
            return PlaylistRef(SPOTIFY, m.group(1))
    for pattern in (_YT_BROWSE, _YT_LIST_PARAM):
        m = pattern.search(text)
        if m:
            return PlaylistRef(YTMUSIC, m.group(1))
    if text.startswith("VL") and _YT_ID.match(text[2:]):
        return PlaylistRef(YTMUSIC, text[2:])
    if _YT_ID.match(text):
        return PlaylistRef(YTMUSIC, text)
    if _SPOTIFY_ID.match(text):
        return PlaylistRef(SPOTIFY, text)
    raise ValueError(f"No reconozco '{text}' como playlist de Spotify ni de YouTube Music.")


def playlist_url(ref: PlaylistRef) -> str:
    if ref.service == SPOTIFY:
        if ref.id == SPOTIFY_LIKED:
            return "https://open.spotify.com/collection/tracks"
        return f"https://open.spotify.com/playlist/{ref.id}"
    return f"https://music.youtube.com/playlist?list={ref.id}"

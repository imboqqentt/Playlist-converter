"""Crea los servicios (Spotify / YouTube Music) con las credenciales correspondientes."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import accounts
from .refs import SPOTIFY, YTMUSIC

SpotifyFactory = Callable[[], object]
YTMusicFactory = Callable[[str | None], object]


def default_spotify_factory():
    from .spotify_service import SpotifyService

    return SpotifyService.from_env()


def default_ytmusic_factory(auth_path: str | None, delay: float = 0.0):
    from .ytmusic_service import YTMusicService

    return YTMusicService.from_auth_file(auth_path, delay=delay)


def ytmusic_auth(account: str | None, auth: str | None = None, required: bool = True) -> str | None:
    """Ruta de la sesión de YouTube Music a usar.

    Con required=False (solo leer una playlist pública) se permite no tener cuenta.
    """
    try:
        return str(accounts.resolve_auth(account, auth))
    except ValueError:
        if required or account or auth:
            raise
        return None


def account_name(auth_path: str | None) -> str | None:
    """Nombre de la cuenta guardada que corresponde a ese archivo (si es una)."""
    if not auth_path:
        return None
    path = Path(auth_path)
    try:
        if path.resolve().parent == accounts.accounts_dir().resolve():
            return path.stem
    except OSError:
        pass
    return None


def build(
    service: str,
    auth_path: str | None,
    spotify_factory: SpotifyFactory | None = None,
    ytmusic_factory: YTMusicFactory | None = None,
):
    if service == SPOTIFY:
        return (spotify_factory or default_spotify_factory)()
    if service == YTMUSIC:
        return (ytmusic_factory or default_ytmusic_factory)(auth_path)
    raise ValueError(f"Servicio desconocido: {service}")

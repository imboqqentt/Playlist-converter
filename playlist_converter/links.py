"""Registro de playlists sincronizadas (origen → destino) para poder actualizarlas.

Se guarda en sincronizadas.json dentro de la carpeta de datos del programa.
Cada vínculo recuerda qué canción del origen corresponde a cuál del destino, así
al actualizar solo se buscan las canciones nuevas.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .refs import SERVICE_NAMES, PlaylistRef, playlist_url

FILE_NAME = "sincronizadas.json"


@dataclass
class SyncLink:
    source_service: str
    source_id: str
    source_name: str
    target_service: str
    target_id: str
    target_name: str
    account: str | None = None  # cuenta de YouTube Music usada (origen o destino)
    strict: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    created: str = field(default_factory=lambda: now())
    last_sync: str | None = None
    track_count: int = 0
    # clave de la canción de origen → {"t": id en destino o None, "n": nombre visible}
    items: dict[str, dict] = field(default_factory=dict)

    @property
    def source(self) -> PlaylistRef:
        return PlaylistRef(self.source_service, self.source_id)

    @property
    def target(self) -> PlaylistRef:
        return PlaylistRef(self.target_service, self.target_id)

    @property
    def source_url(self) -> str:
        return playlist_url(self.source)

    @property
    def target_url(self) -> str:
        return playlist_url(self.target)

    def describe(self) -> str:
        return (
            f"{self.source_name} ({SERVICE_NAMES[self.source_service]}) → "
            f"{self.target_name} ({SERVICE_NAMES[self.target_service]})"
        )


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _path() -> Path:
    from .accounts import app_dir

    return app_dir() / FILE_NAME


def load() -> list[SyncLink]:
    path = _path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    known = SyncLink.__dataclass_fields__
    return [SyncLink(**{k: v for k, v in entry.items() if k in known}) for entry in data]


def save(links: list[SyncLink]) -> None:
    path = _path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps([asdict(l) for l in links], ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def upsert(link: SyncLink) -> SyncLink:
    """Guarda el vínculo; si ya existe uno hacia el mismo destino, lo reemplaza."""
    links = [
        l
        for l in load()
        if l.id != link.id and not (l.target_service == link.target_service and l.target_id == link.target_id)
    ]
    links.append(link)
    save(links)
    return link


def get(link_id: str) -> SyncLink | None:
    return next((l for l in load() if l.id == link_id), None)


def remove(link_id: str) -> bool:
    links = load()
    remaining = [l for l in links if l.id != link_id]
    if len(remaining) == len(links):
        return False
    save(remaining)
    return True

"""Conversión y sincronización de playlists, compartidas por la línea de comandos y la ventana.

`source` y `target` son servicios (SpotifyService o YTMusicService): cualquiera
de los dos puede ser origen o destino.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from .links import SyncLink, now
from .models import MatchResult, MatchStatus, Track
from .refs import PlaylistRef, playlist_url

DESCRIPTION = "Convertida con Playlist Converter"

OnStart = Callable[[str, int], None]
OnResult = Callable[[int, int, MatchResult], None]
OnStatus = Callable[[str], None]


def _noop(*_args) -> None:
    pass


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
    target_service: str | None = None
    added: int = 0
    cancelled: bool = False

    @property
    def playlist_url(self) -> str | None:
        if not self.playlist_id or not self.target_service:
            return None
        return playlist_url(PlaylistRef(self.target_service, self.playlist_id))


@dataclass
class SyncOutcome:
    link: SyncLink
    results: list[MatchResult] = field(default_factory=list)  # canciones nuevas buscadas
    added: int = 0
    removed: list[str] = field(default_factory=list)  # nombres de canciones quitadas del destino
    cancelled: bool = False


def accepted(result: MatchResult, strict: bool) -> bool:
    allowed = {MatchStatus.MATCHED} if strict else {MatchStatus.MATCHED, MatchStatus.LOW_CONFIDENCE}
    return result.status in allowed and result.candidate is not None


def ids_to_add(results: list[MatchResult], strict: bool) -> list[str]:
    return [r.candidate.id for r in results if accepted(r, strict)]


def _search_all(
    tracks: list[Track],
    target,
    on_result: OnResult,
    cancel: threading.Event | None,
) -> tuple[list[MatchResult], bool]:
    results: list[MatchResult] = []
    for i, track in enumerate(tracks, start=1):
        if cancel is not None and cancel.is_set():
            return results, True
        result = target.find(track)
        results.append(result)
        on_result(i, len(tracks), result)
    return results, False


def mapping_from(results: list[MatchResult], strict: bool) -> dict[str, dict]:
    items = {}
    for r in results:
        target_id = r.candidate.id if accepted(r, strict) else None
        items[r.track.key] = {"t": target_id, "n": r.track.display()}
    return items


def convert(
    source,
    target,
    playlist_id: str,
    options: ConvertOptions,
    on_start: OnStart = _noop,
    on_result: OnResult = _noop,
    on_status: OnStatus = _noop,
    cancel: threading.Event | None = None,
) -> ConvertOutcome:
    """Lee la playlist, busca cada canción y (salvo dry_run) crea la playlist en el destino.

    Si `cancel` se activa, se detiene antes de modificar el destino.
    """
    name = options.name or source.playlist_name(playlist_id)
    on_status(f"Leyendo «{name}»...")
    tracks = list(source.tracks(playlist_id))
    if options.limit:
        tracks = tracks[: options.limit]

    outcome = ConvertOutcome(playlist_name=name, target_service=target.service)
    on_start(name, len(tracks))
    outcome.results, outcome.cancelled = _search_all(tracks, target, on_result, cancel)
    if outcome.cancelled:
        return outcome

    item_ids = ids_to_add(outcome.results, options.strict)
    if options.dry_run or not item_ids:
        return outcome

    on_status("Creando la playlist...")
    if options.append_to:
        outcome.playlist_id = options.append_to
    else:
        outcome.playlist_id = target.create_playlist(name, DESCRIPTION, options.privacy)
    target.add_items(outcome.playlist_id, item_ids)
    outcome.added = len(set(item_ids))
    return outcome


def link_from_outcome(
    outcome: ConvertOutcome,
    source_service: str,
    source_id: str,
    source_name: str,
    account: str | None,
    strict: bool,
) -> SyncLink:
    """Crea el vínculo de sincronización a partir de una conversión terminada."""
    return SyncLink(
        source_service=source_service,
        source_id=source_id,
        source_name=source_name,
        target_service=outcome.target_service,
        target_id=outcome.playlist_id,
        target_name=outcome.playlist_name,
        account=account,
        strict=strict,
        last_sync=now(),
        track_count=len(outcome.results),
        items=mapping_from(outcome.results, strict),
    )


def sync(
    link: SyncLink,
    source,
    target,
    remove_missing: bool = False,
    on_start: OnStart = _noop,
    on_result: OnResult = _noop,
    on_status: OnStatus = _noop,
    cancel: threading.Event | None = None,
) -> SyncOutcome:
    """Actualiza el destino con las canciones nuevas del origen.

    - Solo se buscan las canciones que no se habían sincronizado (o que antes no se encontraron).
    - Nunca se agrega una canción que ya está en el destino, así no hay duplicados.
    - Con remove_missing, se quitan del destino las canciones que ya no están en el origen.
    - Si el usuario borró a mano una canción del destino, no se vuelve a agregar.
    Modifica `link` (mapeo, fecha, cantidad); quien llama decide si guardarlo.
    """
    outcome = SyncOutcome(link=link)
    on_status(f"Leyendo «{link.source_name}»...")
    tracks = list(source.tracks(link.source_id))
    source_keys = {t.key for t in tracks}
    known = link.items

    pending: list[Track] = []
    seen: set[str] = set()
    for t in tracks:
        if t.key in seen:
            continue
        seen.add(t.key)
        if t.key not in known or not known[t.key].get("t"):
            pending.append(t)

    on_status(f"Revisando «{link.target_name}»...")
    present = set(target.playlist_item_ids(link.target_id))

    on_start(link.source_name, len(pending))
    outcome.results, outcome.cancelled = _search_all(pending, target, on_result, cancel)
    if outcome.cancelled:
        return outcome

    to_add = [i for i in dict.fromkeys(ids_to_add(outcome.results, link.strict)) if i not in present]
    if to_add:
        on_status(f"Agregando {len(to_add)} canciones...")
        target.add_items(link.target_id, to_add)
    outcome.added = len(to_add)
    for r in outcome.results:
        target_id = r.candidate.id if accepted(r, link.strict) else None
        known[r.track.key] = {"t": target_id, "n": r.track.display()}

    gone = [k for k in known if k not in source_keys]
    if remove_missing and gone:
        still_used = {v.get("t") for k, v in known.items() if k in source_keys}
        to_remove = [
            known[k]["t"]
            for k in gone
            if known[k].get("t") and known[k]["t"] in present and known[k]["t"] not in still_used
        ]
        if to_remove:
            on_status(f"Quitando {len(to_remove)} canciones...")
            target.remove_items(link.target_id, to_remove)
        outcome.removed = [known[k].get("n", k) for k in gone if known[k].get("t") in set(to_remove)]
    if remove_missing:
        for k in gone:
            known.pop(k, None)

    link.last_sync = now()
    link.track_count = len(tracks)
    return outcome

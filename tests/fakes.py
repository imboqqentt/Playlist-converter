"""Servicio falso en memoria que sirve como origen o destino en los tests."""

from playlist_converter.models import Candidate, MatchResult, MatchStatus, Track


def track(title, artist="Artist", key=None):
    return Track(title, (artist,), 200, source_id=key or f"src-{title}")


class FakeService:
    """Playlists en memoria. `catalog` es lo que se puede encontrar al buscar (título → id)."""

    def __init__(self, service, playlists=None, catalog=None, names=None):
        self.service = service
        self.playlists = {pid: list(items) for pid, items in (playlists or {}).items()}
        self.catalog = dict(catalog or {})
        self.names = dict(names or {})
        self.searched = []
        self.created = []
        self.removed = []

    # origen
    def playlist_name(self, pid):
        return self.names.get(pid, f"Lista {pid}")

    def tracks(self, pid):
        return iter(self.playlists[pid])

    # destino
    def find(self, t):
        self.searched.append(t.title)
        item_id = self.catalog.get(t.title)
        if not item_id:
            return MatchResult(t, MatchStatus.NOT_FOUND, None, 0.1)
        return MatchResult(t, MatchStatus.MATCHED, Candidate(item_id, t.title, t.artists, 200), 0.95)

    def create_playlist(self, name, description, privacy):
        pid = f"new{len(self.created) + 1}"
        self.created.append((name, privacy))
        self.playlists[pid] = []
        self.names[pid] = name
        return pid

    def add_items(self, pid, ids):
        for item_id in dict.fromkeys(ids):
            self.playlists[pid].append(Track(item_id, ("x",), 200, source_id=item_id))

    def playlist_item_ids(self, pid):
        return [t.source_id for t in self.playlists[pid]]

    def remove_items(self, pid, ids):
        self.removed.extend(ids)
        self.playlists[pid] = [t for t in self.playlists[pid] if t.source_id not in set(ids)]

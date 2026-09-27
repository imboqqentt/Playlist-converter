from fakes import FakeService, track

from playlist_converter import links
from playlist_converter.converter import ConvertOptions, convert, link_from_outcome, sync
from playlist_converter.links import SyncLink


def make_pair(source_tracks, catalog):
    source = FakeService("spotify", playlists={"SRC": source_tracks}, names={"SRC": "Origen"})
    target = FakeService("ytmusic", catalog=catalog)
    return source, target


def convert_and_link(source, target, strict=False):
    outcome = convert(source, target, "SRC", ConvertOptions(strict=strict))
    return outcome, link_from_outcome(outcome, "spotify", "SRC", "Origen", "daniel", strict)


def test_convert_creates_link_with_mapping():
    source, target = make_pair([track("A"), track("B"), track("C")], {"A": "yA", "B": "yB"})
    outcome, link = convert_and_link(source, target)
    assert outcome.playlist_id == "new1"
    assert target.playlist_item_ids("new1") == ["yA", "yB"]
    assert link.items["src-A"]["t"] == "yA"
    assert link.items["src-C"]["t"] is None  # no encontrada: se reintenta al actualizar
    assert (link.target_id, link.account, link.track_count) == ("new1", "daniel", 3)


def test_sync_adds_only_new_songs():
    source, target = make_pair([track("A"), track("B")], {"A": "yA", "B": "yB", "D": "yD"})
    _, link = convert_and_link(source, target)
    target.searched.clear()

    source.playlists["SRC"].append(track("D"))
    result = sync(link, source, target)
    assert target.searched == ["D"]  # A y B no se vuelven a buscar
    assert result.added == 1
    assert target.playlist_item_ids("new1") == ["yA", "yB", "yD"]
    assert link.track_count == 3 and link.last_sync


def test_sync_retries_not_found_and_never_duplicates():
    source, target = make_pair([track("A"), track("C")], {"A": "yA"})
    _, link = convert_and_link(source, target)
    target.catalog["C"] = "yC"  # ahora sí se encuentra
    target.searched.clear()
    result = sync(link, source, target)
    assert target.searched == ["C"]
    assert result.added == 1
    # una segunda actualización no hace nada
    target.searched.clear()
    again = sync(link, source, target)
    assert (target.searched, again.added) == ([], 0)
    assert target.playlist_item_ids("new1") == ["yA", "yC"]


def test_sync_of_linked_existing_playlist_skips_songs_already_there():
    source, target = make_pair([track("A"), track("B")], {"A": "yA", "B": "yB"})
    target.playlists["EXIST"] = [track("yA", key="yA")]  # ya tenía A
    link = SyncLink("spotify", "SRC", "Origen", "ytmusic", "EXIST", "Existente")
    result = sync(link, source, target)
    assert result.added == 1
    assert target.playlist_item_ids("EXIST") == ["yA", "yB"]
    assert link.items["src-A"]["t"] == "yA"


def test_sync_remove_missing():
    source, target = make_pair([track("A"), track("B")], {"A": "yA", "B": "yB"})
    _, link = convert_and_link(source, target)
    source.playlists["SRC"] = [track("A")]  # se borró B del origen

    kept = sync(link, source, target, remove_missing=False)
    assert kept.removed == [] and target.playlist_item_ids("new1") == ["yA", "yB"]

    removed = sync(link, source, target, remove_missing=True)
    assert removed.removed == ["Artist - B"]
    assert target.playlist_item_ids("new1") == ["yA"]
    assert "src-B" not in link.items


def test_sync_does_not_readd_songs_deleted_by_hand_from_target():
    source, target = make_pair([track("A"), track("B")], {"A": "yA", "B": "yB"})
    _, link = convert_and_link(source, target)
    target.remove_items("new1", ["yB"])  # el usuario la borró en el destino
    result = sync(link, source, target)
    assert result.added == 0
    assert target.playlist_item_ids("new1") == ["yA"]


def test_sync_strict_skips_doubtful_matches():
    from playlist_converter.models import MatchResult, MatchStatus, Candidate

    source, target = make_pair([track("A")], {})

    def doubtful(t):
        return MatchResult(t, MatchStatus.LOW_CONFIDENCE, Candidate("yA", "A", ("x",)), 0.6)

    target.find = doubtful
    target.playlists["T"] = []
    link = SyncLink("spotify", "SRC", "Origen", "ytmusic", "T", "T", strict=True)
    assert sync(link, source, target).added == 0
    link.strict = False
    assert sync(link, source, target).added == 1


def test_sync_cancel_changes_nothing():
    import threading

    source, target = make_pair([track("A")], {"A": "yA"})
    target.playlists["T"] = []
    link = SyncLink("spotify", "SRC", "Origen", "ytmusic", "T", "T")
    cancel = threading.Event()
    cancel.set()
    result = sync(link, source, target, cancel=cancel)
    assert result.cancelled and target.playlists["T"] == [] and link.last_sync is None


def test_links_store():
    first = links.upsert(SyncLink("spotify", "S1", "Uno", "ytmusic", "T1", "Uno YT"))
    second = links.upsert(SyncLink("ytmusic", "S2", "Dos", "spotify", "T2", "Dos SP", account="mama"))
    assert [l.id for l in links.load()] == [first.id, second.id]
    # un nuevo vínculo hacia el mismo destino reemplaza al anterior
    links.upsert(SyncLink("spotify", "S3", "Tres", "ytmusic", "T1", "Uno YT"))
    loaded = links.load()
    assert [l.source_id for l in loaded] == ["S2", "S3"]
    assert links.get(second.id).account == "mama"
    assert "Dos (YouTube Music) → Dos SP (Spotify)" == second.describe()
    assert links.remove(second.id) and not links.remove(second.id)

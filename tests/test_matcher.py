from playlist_converter import matcher
from playlist_converter.models import Candidate, Track

BOHEMIAN = Track(
    title="Bohemian Rhapsody - Remastered 2011",
    artists=("Queen",),
    duration_seconds=354,
    album="A Night At The Opera",
)


def cand(title, artists=("Queen",), duration=354, result_type="song", video_id="x"):
    return Candidate(video_id, title, tuple(artists), duration, result_type)


def test_clean_title_removes_decorations():
    assert matcher.clean_title("Bohemian Rhapsody - Remastered 2011") == "Bohemian Rhapsody"
    assert matcher.clean_title("Despacito (feat. Daddy Yankee)") == "Despacito"
    assert matcher.clean_title("Heroes (2017 Remaster)") == "Heroes"
    assert matcher.clean_title("Ella - En Vivo") == "Ella - En Vivo"


def test_normalize_strips_accents_and_punctuation():
    assert matcher.normalize("Canción Ñoña, ¡Sí!") == "cancion nona si"


def test_build_query_uses_primary_artist_and_clean_title():
    track = Track("Despacito (feat. Daddy Yankee)", ("Luis Fonsi", "Daddy Yankee"))
    assert matcher.build_query(track) == "Luis Fonsi Despacito"


def test_exact_song_is_matched():
    _, s = matcher.best_candidate(BOHEMIAN, [cand("Bohemian Rhapsody")])
    assert s >= matcher.MATCH_THRESHOLD


def test_official_video_title_format_is_matched():
    video = cand("Queen – Bohemian Rhapsody (Official Video Remastered)", artists=("Queen Official",),
                 duration=359, result_type="video")
    assert matcher.score(BOHEMIAN, video) >= matcher.MATCH_THRESHOLD


def test_live_version_loses_against_studio_version():
    studio = cand("Bohemian Rhapsody", video_id="studio")
    live = cand("Bohemian Rhapsody (Live Aid 1985)", duration=360, video_id="live")
    best, _ = matcher.best_candidate(BOHEMIAN, [live, studio])
    assert best.video_id == "studio"


def test_live_track_on_spotify_is_not_penalized():
    track = Track("Ella - En Vivo", ("José José",), 250)
    assert matcher.variant_penalty(track, cand("Ella (En Vivo)", ("José José",), 250)) == 0


def test_cover_by_other_artist_is_rejected():
    cover = cand("Bohemian Rhapsody (Cover)", artists=("Random Band",), duration=340)
    assert matcher.score(BOHEMIAN, cover) < matcher.LOW_CONFIDENCE_THRESHOLD


def test_wrong_song_same_artist_is_not_matched():
    other = cand("Don't Stop Me Now", duration=209)
    assert matcher.score(BOHEMIAN, other) < matcher.MATCH_THRESHOLD


def test_duration_score_bands():
    t = Track("x", ("a",), 200)
    assert matcher.duration_score(t, cand("x", duration=202)) == 1.0
    assert matcher.duration_score(t, cand("x", duration=260)) == 0.0
    assert matcher.duration_score(t, cand("x", duration=None)) == 0.5


def test_featured_artist_counts_partially():
    track = Track("Song", ("Main Artist", "Guest"), 180)
    assert matcher.artist_score(track, cand("Song", artists=("Guest",))) == 0.6


def test_best_candidate_empty_list():
    assert matcher.best_candidate(BOHEMIAN, []) == (None, 0.0)


def test_official_channel_beats_third_party_lyrics_upload():
    lyrics = cand("Queen - Bohemian Rhapsody (Lyrics)", artists=("7clouds Rock",), duration=355,
                  result_type="video", video_id="lyrics")
    official = cand("Queen – Bohemian Rhapsody (Official Video Remastered)", artists=("Queen Official",),
                    duration=359, result_type="video", video_id="official")
    best, _ = matcher.best_candidate(BOHEMIAN, [lyrics, official])
    assert best.video_id == "official"


def test_cover_with_very_different_length_is_rejected():
    track = Track("Despacito (feat. Daddy Yankee)", ("Luis Fonsi", "Daddy Yankee"), 229)
    cover = cand("Forestella - Despacito (original: Luis Fonsi) | Live Wire", artists=(), duration=276,
                 result_type="video")
    assert matcher.score(track, cover) < matcher.LOW_CONFIDENCE_THRESHOLD


def test_karaoke_is_rejected_even_with_matching_duration():
    track = Track("Despacito (feat. Daddy Yankee)", ("Luis Fonsi", "Daddy Yankee"), 229)
    karaoke = cand("Despacito - Luis Fonsi & Daddy Yankee | Versión Karaoke | KaraFun",
                   artists=("KaraFun Karaoke",), duration=230, result_type="video")
    assert matcher.score(track, karaoke) < matcher.LOW_CONFIDENCE_THRESHOLD


def test_acoustic_version_is_not_a_confident_match():
    track = Track("La Flaca", ("Jarabe De Palo",), 263, "La Flaca")
    acoustic = cand("La flaca (acústica)", artists=("Jarabe De Palo",), duration=269)
    assert matcher.score(track, acoustic) < matcher.MATCH_THRESHOLD

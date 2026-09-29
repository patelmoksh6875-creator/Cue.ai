from matching import candidates
from sources.deezer import DeezerTrack

import pytest


def _track(id, title, artist_id=1, artist_name="Artist", isrc=None, bpm=None):
    return DeezerTrack(
        id=id,
        title=title,
        artist_id=artist_id,
        artist_name=artist_name,
        album_id=1,
        duration=200,
        bpm=bpm,
        isrc=isrc,
    )


def test_normalize_title_strips_feature_credits():
    assert candidates.normalize_title("Get Lucky (feat. Pharrell Williams)") == "get lucky"


def test_normalize_title_strips_version_tags():
    assert candidates.normalize_title("One More Time (Radio Edit)") == "one more time"
    assert candidates.normalize_title("Everlong (Live)") == "everlong"


def test_normalize_title_strips_punctuation_and_case():
    assert candidates.normalize_title("Don't Stop Believin'!") == "dont stop believin"


def test_dedupe_by_isrc():
    tracks = [
        _track(1, "Song A", isrc="ABC123"),
        _track(2, "Song A (Radio Edit)", isrc="ABC123"),
    ]
    result = candidates._dedupe(tracks)
    assert len(result) == 1


def test_dedupe_by_normalized_title_when_no_isrc():
    tracks = [
        _track(1, "Song B", artist_id=5),
        _track(2, "Song B (Remix)", artist_id=5),
    ]
    result = candidates._dedupe(tracks)
    assert len(result) == 1


def test_dedupe_keeps_distinct_tracks():
    tracks = [_track(1, "Song A", isrc="AAA"), _track(2, "Song B", isrc="BBB")]
    result = candidates._dedupe(tracks)
    assert len(result) == 2


def test_hard_filter_bpm_keeps_within_tolerance():
    pool = [_track(1, "A", bpm=128), _track(2, "B", bpm=129)]
    kept = candidates.hard_filter_bpm(128, pool)
    assert len(kept) == 2


def test_hard_filter_bpm_drops_far_off():
    pool = [_track(1, "A", bpm=128), _track(2, "B", bpm=200)]
    kept = candidates.hard_filter_bpm(128, pool)
    ids = {t.id for t in kept}
    assert 1 in ids and 2 not in ids


def test_hard_filter_bpm_keeps_missing_bpm_for_later_analysis():
    pool = [_track(1, "A", bpm=None)]
    kept = candidates.hard_filter_bpm(128, pool)
    assert len(kept) == 1


def test_hard_filter_bpm_no_seed_bpm_keeps_everything():
    pool = [_track(1, "A", bpm=999)]
    kept = candidates.hard_filter_bpm(None, pool)
    assert len(kept) == 1


def test_apply_diversity_caps_per_artist():
    from matching.scoring import ScoreBreakdown

    def breakdown(score):
        return ScoreBreakdown(bpm=1, key=1, tags=1, genre=1, energy=1, total=score, label="safe")

    ranked = [
        candidates.RankedResult(track=_track(1, "A", artist_id=1), breakdown=breakdown(0.9)),
        candidates.RankedResult(track=_track(2, "B", artist_id=1), breakdown=breakdown(0.8)),
        candidates.RankedResult(track=_track(3, "C", artist_id=1), breakdown=breakdown(0.7)),
        candidates.RankedResult(track=_track(4, "D", artist_id=2), breakdown=breakdown(0.6)),
    ]
    kept = candidates._apply_diversity(ranked, max_per_artist=2)
    artist_1_count = sum(1 for r in kept if r.track.artist_id == 1)
    assert artist_1_count == 2
    assert len(kept) == 3


# --- resolve_to_deezer (fuzzy matching) -------------------------------------


def test_resolve_to_deezer_picks_best_fuzzy_match(monkeypatch):
    candidates_pool = [
        _track(1, "One More Time", artist_name="Daft Punk"),
        _track(2, "Around the World", artist_name="Daft Punk"),
    ]
    monkeypatch.setattr(
        candidates.deezer, "search_tracks", lambda query, limit=5: candidates_pool
    )
    result = candidates.resolve_to_deezer("Daft Punk", "One More Time (feat. Nobody)")
    assert result.id == 1


def test_resolve_to_deezer_handles_punctuation_differences(monkeypatch):
    candidates_pool = [_track(1, "Don't Stop Believin'", artist_name="Journey")]
    monkeypatch.setattr(
        candidates.deezer, "search_tracks", lambda query, limit=5: candidates_pool
    )
    result = candidates.resolve_to_deezer("Journey", "Dont Stop Believin")
    assert result is not None
    assert result.id == 1


def test_resolve_to_deezer_returns_none_below_threshold(monkeypatch):
    candidates_pool = [_track(1, "Completely Different Song", artist_name="Someone Else")]
    monkeypatch.setattr(
        candidates.deezer, "search_tracks", lambda query, limit=5: candidates_pool
    )
    result = candidates.resolve_to_deezer("Daft Punk", "One More Time")
    assert result is None


def test_resolve_to_deezer_returns_none_when_no_results(monkeypatch):
    monkeypatch.setattr(candidates.deezer, "search_tracks", lambda query, limit=5: [])
    result = candidates.resolve_to_deezer("Nobody", "Nothing")
    assert result is None

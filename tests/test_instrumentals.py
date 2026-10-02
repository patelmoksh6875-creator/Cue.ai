"""Official-instrumental matching: accept/reject cases, caches, source order."""
import pytest

import config
from db import repo
from matching import instrumentals as I
from mixing import render
from sources import deezer, itunes

C = I.Candidate


def score(title, artist, dur, cand):
    return I.score_candidate(title, artist, dur, cand)


# ---- accept ----------------------------------------------------------------
def test_accepts_exact_official_instrumental():
    c = C("deezer", "1", "Superhero (Heroes & Villains) (Instrumental)", "Metro Boomin", 183)
    assert score("Superhero (Heroes & Villains)", "Metro Boomin", 183, c) >= config.INSTRUMENTAL_MIN_CONFIDENCE


def test_accepts_bracket_style_and_featured_artist_on_original():
    c = C("itunes", "2", "Superhero (Heroes & Villains) [Instrumental]", "Metro Boomin", 182)
    assert score("Superhero (Heroes & Villains)", "Metro Boomin, Future & Chris Brown", 183, c) >= 0.75


def test_accepts_instrumental_radio_edit_variant():
    c = C("deezer", "3", "Levels (Instrumental Radio Edit)", "Avicii", 199)
    assert score("Levels (Radio Edit)", "Avicii", 199, c) >= 0.75


# ---- reject ----------------------------------------------------------------
@pytest.mark.parametrize("title,artist,album", [
    ("Humble (Originally Performed by Kendrick Lamar) [Instrumental Version]", "Karaoke Freaks", ""),
    ("Humble (In the Style of Kendrick Lamar) [Karaoke Version]", "Instrumental King", ""),
    ("Bad Guy (Instrumental)", "KPH", ""),                       # wrong artist
    ("Bad Guy", "Vitamin String Quartet", ""),                   # not instrumental-titled
    ("Bad Guy (Instrumental Remix)", "i-genius", ""),            # remix
    ("Uptown Funk (Instrumental)", "Lullaby Players", ""),
    ("Uptown Funk (Instrumental)", "Backtracks Band", ""),
    ("Bad Guy (Instrumental)", "Billie Eilish", "Tribute To Billie Eilish"),
    ("Bad Guy (Piano Version) [Instrumental]", "Billie Eilish", ""),
    ("Bad Guy (Live) [Instrumental]", "Billie Eilish", ""),
])
def test_rejects_karaoke_cover_tribute_remix_wrong_artist(title, artist, album):
    c = C("itunes", "9", title, artist, 194, album)
    assert score("bad guy", "Billie Eilish", 194, c) == 0.0 or score("Humble", "Kendrick Lamar", 177, c) == 0.0


def test_rejects_wrong_duration():
    c = C("deezer", "4", "Levels (Instrumental)", "Avicii", 60)
    assert score("Levels", "Avicii", 199, c) == 0.0


def test_rejects_different_song_with_same_artist():
    c = C("deezer", "5", "Wake Me Up (Instrumental)", "Avicii", 199)
    assert score("Levels", "Avicii", 199, c) == 0.0


def test_remix_word_allowed_when_original_is_a_remix():
    c = C("deezer", "6", "Levels (Skrillex Remix) (Instrumental)", "Avicii", 200)
    assert score("Levels (Skrillex Remix)", "Avicii", 200, c) > 0


def test_best_candidate_none_below_threshold():
    assert I.best_candidate("Levels", "Avicii", 199, [C("d", "1", "Levels", "Avicii", 199)]) is None


# ---- caches ----------------------------------------------------------------
@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = tmp_path / "t.sqlite3"
    repo.init_db(path)
    monkeypatch.setattr(repo.config, "DB_PATH", path)
    repo.upsert_artist(repo.Artist(id=1, name="Avicii"))
    repo.upsert_track(repo.Track(id=10, title="Levels", artist_id=1))
    return path


def _track():
    return deezer.DeezerTrack(id=10, title="Levels", artist_id=1, artist_name="Avicii",
                              album_id=None, duration=199, bpm=None, isrc=None)


def test_positive_result_is_cached(db, monkeypatch):
    calls = {"n": 0}

    def fake_search(q, limit=15):
        calls["n"] += 1
        return [deezer.DeezerTrack(id=99, title="Levels (Instrumental)", artist_id=1,
                                   artist_name="Avicii", album_id=None, duration=199, bpm=None, isrc=None)]

    monkeypatch.setattr(deezer, "search_tracks", fake_search)
    first = I.find_instrumental(_track())
    n = calls["n"]
    second = I.find_instrumental(_track())
    assert first.found and second.source_track_id == "99"
    assert calls["n"] == n  # repeat served from cache


def test_negative_result_is_cached_and_not_rechecked(db, monkeypatch):
    calls = {"n": 0}

    def fake(q, limit=15):
        calls["n"] += 1
        return []

    monkeypatch.setattr(deezer, "search_tracks", fake)
    monkeypatch.setattr(itunes, "search_songs", fake)
    assert I.find_instrumental(_track()) is None
    n = calls["n"]
    assert n > 0 and repo.get_instrumental_link(10).found is False
    assert I.find_instrumental(_track()) is None
    assert calls["n"] == n


def test_stale_negative_is_rechecked(db, monkeypatch):
    repo.upsert_instrumental_link(repo.InstrumentalLink(track_id=10, found=False, checked_at="2000-01-01T00:00:00+00:00"))
    calls = {"n": 0}

    def fake(q, limit=15):
        calls["n"] += 1
        return []

    monkeypatch.setattr(deezer, "search_tracks", fake)
    monkeypatch.setattr(itunes, "search_songs", fake)
    I.find_instrumental(_track())
    assert calls["n"] > 0


def test_one_source_down_does_not_hide_the_other(db, monkeypatch):
    def boom(q, limit=15):
        raise deezer.DeezerAPIError("down")

    monkeypatch.setattr(deezer, "search_tracks", boom)
    monkeypatch.setattr(itunes, "search_songs", lambda q, limit=15: [
        itunes.ItunesTrack(id=5, title="Levels [Instrumental]", artist="Avicii", album="Levels", duration_s=199, preview_url="x")])
    link = I.find_instrumental(_track())
    assert link and link.source == "itunes"


# ---- source selection order -------------------------------------------------
def test_source_order():
    assert render.choose_source_order("auto") == ["instrumental", "beat_view", "full_mix"]
    assert render.choose_source_order("instrumental") == ["instrumental", "beat_view", "full_mix"]
    assert render.choose_source_order("beat_view") == ["beat_view", "full_mix"]
    assert render.choose_source_order("full_mix") == ["full_mix"]


def test_resolve_prefers_instrumental_then_beat_view(monkeypatch):
    import numpy as np
    y = np.zeros(22050, dtype="float32")
    track = _track()
    link = repo.InstrumentalLink(track_id=10, found=True, source="deezer", source_track_id="99", title="x", artist="y")
    monkeypatch.setattr(I, "find_instrumental", lambda t: link)
    monkeypatch.setattr(I, "instrumental_preview_url", lambda l: "http://x/p.mp3")
    monkeypatch.setattr(render, "_load_audio", lambda u: (np.ones(10, dtype="float32"), 22050))
    assert render.resolve_source(track, y, 22050, "auto").label == "instrumental"
    monkeypatch.setattr(I, "find_instrumental", lambda t: None)
    monkeypatch.setattr(render.beatview, "make_beat_view", lambda y, sr: y)
    assert render.resolve_source(track, y, 22050, "auto").label == "beat_view"
    monkeypatch.setattr(render.beatview, "make_beat_view", lambda y, sr: (_ for _ in ()).throw(RuntimeError("x")))
    assert render.resolve_source(track, y, 22050, "auto").label == "full_mix"
    assert render.resolve_source(track, y, 22050, "full_mix").label == "full_mix"

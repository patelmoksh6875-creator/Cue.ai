import sqlite3
from pathlib import Path

import pytest

from db import repo


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "test.sqlite3"
    repo.init_db(path)
    return path


@pytest.fixture()
def conn(db_path, monkeypatch):
    monkeypatch.setattr(repo.config, "DB_PATH", db_path)
    return db_path


def test_init_db_creates_tables(db_path):
    with sqlite3.connect(db_path) as c:
        tables = {
            r[0]
            for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    expected = {
        "schema_version",
        "artists",
        "albums",
        "tracks",
        "tags",
        "audio_features",
        "match_runs",
    }
    assert expected.issubset(tables)


def test_init_db_is_idempotent(db_path):
    repo.init_db(db_path)  # second call should not raise
    with sqlite3.connect(db_path) as c:
        row = c.execute("SELECT COUNT(*) FROM schema_version").fetchone()
        assert row[0] == 1


def test_artist_round_trip(conn):
    artist = repo.Artist(id=1, name="Daft Punk")
    repo.upsert_artist(artist)
    fetched = repo.get_artist(1)
    assert fetched == artist


def test_album_round_trip(conn):
    album = repo.Album(id=10, title="Discovery", genre="Electronic")
    repo.upsert_album(album)
    fetched = repo.get_album(10)
    assert fetched == album


def test_track_round_trip(conn):
    repo.upsert_artist(repo.Artist(id=1, name="Daft Punk"))
    repo.upsert_album(repo.Album(id=10, title="Discovery", genre="Electronic"))
    track = repo.Track(
        id=100,
        title="One More Time",
        artist_id=1,
        album_id=10,
        isrc="GBDUW9900001",
        duration=320,
        deezer_bpm=123.0,
    )
    repo.upsert_track(track)
    fetched = repo.get_track(100)
    assert fetched.title == "One More Time"
    assert fetched.deezer_bpm == 123.0

    by_isrc = repo.get_track_by_isrc("GBDUW9900001")
    assert by_isrc.id == 100


def test_track_upsert_updates_existing(conn):
    repo.upsert_artist(repo.Artist(id=1, name="Daft Punk"))
    repo.upsert_track(repo.Track(id=100, title="Original", artist_id=1))
    repo.upsert_track(repo.Track(id=100, title="Updated", artist_id=1))
    assert repo.get_track(100).title == "Updated"


def test_tags_round_trip(conn):
    repo.upsert_artist(repo.Artist(id=1, name="Daft Punk"))
    repo.upsert_track(repo.Track(id=100, title="One More Time", artist_id=1))
    repo.upsert_tags(
        [
            repo.Tag(track_id=100, tag="house", weight=0.9, source="lastfm"),
            repo.Tag(track_id=100, tag="dance", weight=0.7, source="lastfm"),
        ]
    )
    tags = repo.get_tags(100)
    assert {t.tag for t in tags} == {"house", "dance"}


def test_audio_features_round_trip(conn):
    repo.upsert_artist(repo.Artist(id=1, name="Daft Punk"))
    repo.upsert_track(repo.Track(id=100, title="One More Time", artist_id=1))
    features = repo.AudioFeatures(
        track_id=100,
        bpm_verified=123.4,
        bpm_confidence=0.9,
        key="C",
        camelot="8B",
        energy=0.8,
        analyzer_version=1,
    )
    repo.upsert_audio_features(features)
    fetched = repo.get_audio_features(100)
    assert fetched.camelot == "8B"
    assert fetched.bpm_verified == 123.4


def test_match_run_log_and_fetch(conn):
    repo.upsert_artist(repo.Artist(id=1, name="Daft Punk"))
    repo.upsert_track(repo.Track(id=100, title="Seed", artist_id=1))
    repo.upsert_track(repo.Track(id=101, title="Candidate", artist_id=1))
    run_id = repo.log_match_run(
        repo.MatchRun(
            seed_id=100,
            candidate_id=101,
            total_score=0.85,
            bpm_score=0.9,
            key_score=0.8,
            label="safe",
        )
    )
    assert run_id is not None
    runs = repo.get_match_runs_for_seed(100)
    assert len(runs) == 1
    assert runs[0].candidate_id == 101
    assert runs[0].total_score == 0.85


def test_connection_self_heals_when_db_file_is_wiped(tmp_path, monkeypatch):
    path = tmp_path / "wiped.sqlite3"
    repo.init_db(path)
    path.write_bytes(b"")  # simulate the file being deleted/emptied under a live server
    monkeypatch.setattr(repo.config, "DB_PATH", path)
    repo.upsert_artist(repo.Artist(id=1, name="A"))
    assert repo.get_artist(1).name == "A"


def test_v1_audio_features_migrates_to_per_source(tmp_path, monkeypatch):
    import sqlite3

    path = tmp_path / "v1.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version VALUES (1);
        CREATE TABLE artists (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE albums (id INTEGER PRIMARY KEY, title TEXT NOT NULL, genre TEXT);
        CREATE TABLE tracks (id INTEGER PRIMARY KEY, isrc TEXT, title TEXT NOT NULL,
            artist_id INTEGER NOT NULL, album_id INTEGER, duration INTEGER, deezer_bpm REAL, fetched_at TEXT NOT NULL);
        CREATE TABLE audio_features (track_id INTEGER PRIMARY KEY, bpm_verified REAL, bpm_confidence REAL,
            key TEXT, camelot TEXT, energy REAL, analyzer_version INTEGER NOT NULL, analyzed_at TEXT NOT NULL);
        INSERT INTO artists VALUES (1,'A'); INSERT INTO tracks VALUES (5,NULL,'T',1,NULL,NULL,NULL,'x');
        INSERT INTO audio_features VALUES (5,120.0,0.5,'C major','8B',0.5,1,'x');
        """
    )
    conn.commit(); conn.close()
    repo.init_db(path)
    monkeypatch.setattr(repo.config, "DB_PATH", path)
    old = repo.get_audio_features(5)
    assert old.audio_source == "full_mix" and old.bpm_verified == 120.0
    repo.upsert_audio_features(repo.AudioFeatures(track_id=5, audio_source="instrumental", bpm_verified=60.0))
    assert repo.get_audio_features(5, "instrumental").bpm_verified == 60.0
    assert repo.get_audio_features(5).bpm_verified == 120.0  # sources don't overwrite each other


def test_instrumental_link_round_trip_including_negative(tmp_path, monkeypatch):
    path = tmp_path / "i.sqlite3"
    repo.init_db(path)
    monkeypatch.setattr(repo.config, "DB_PATH", path)
    repo.upsert_artist(repo.Artist(id=1, name="A"))
    repo.upsert_track(repo.Track(id=1, title="T", artist_id=1))
    repo.upsert_instrumental_link(repo.InstrumentalLink(track_id=1, found=False))
    assert repo.get_instrumental_link(1).found is False
    repo.upsert_instrumental_link(repo.InstrumentalLink(track_id=1, found=True, source="itunes", source_track_id="9", title="x", confidence=0.9))
    assert repo.get_instrumental_link(1).source == "itunes"

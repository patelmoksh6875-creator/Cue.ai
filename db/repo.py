"""The ONLY module that touches SQL. Everything else calls these functions
with plain dicts/dataclasses in and out.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

import config

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
CURRENT_SCHEMA_VERSION = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_connection(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Self-heal: if the DB file was deleted/replaced while the server was
    # running, SQLite silently makes an empty one with no tables. Recreate
    # the schema instead of failing every request with "no such table".
    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='tracks'").fetchone() is None:
        _apply_schema(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _apply_schema(conn: sqlite3.Connection) -> None:
    """Create missing tables, migrate older layouts, stamp the version."""
    conn.executescript(SCHEMA_PATH.read_text())
    cols = [r[1] for r in conn.execute("PRAGMA table_info(audio_features)")]
    if "audio_source" not in cols:
        # v1 -> v2: audio_features gains audio_source and a composite key.
        conn.executescript(
            """
            ALTER TABLE audio_features RENAME TO audio_features_v1;
            CREATE TABLE audio_features (
                track_id INTEGER NOT NULL REFERENCES tracks(id),
                audio_source TEXT NOT NULL DEFAULT 'full_mix',
                bpm_verified REAL, bpm_confidence REAL, key TEXT, camelot TEXT, energy REAL,
                analyzer_version INTEGER NOT NULL, analyzed_at TEXT NOT NULL,
                PRIMARY KEY (track_id, audio_source)
            );
            INSERT INTO audio_features
                (track_id, audio_source, bpm_verified, bpm_confidence, key, camelot, energy,
                 analyzer_version, analyzed_at)
            SELECT track_id, 'full_mix', bpm_verified, bpm_confidence, key, camelot, energy,
                   analyzer_version, analyzed_at FROM audio_features_v1;
            DROP TABLE audio_features_v1;
            """
        )
    if conn.execute("SELECT 1 FROM schema_version").fetchone() is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (CURRENT_SCHEMA_VERSION,))
    else:
        conn.execute("UPDATE schema_version SET version = ?", (CURRENT_SCHEMA_VERSION,))
    conn.commit()


def init_db(db_path: Path | str | None = None) -> None:
    """Create all tables if they don't exist, migrate old ones, stamp the version."""
    with get_connection(db_path) as conn:
        _apply_schema(conn)


# --- Dataclasses -------------------------------------------------------


@dataclass
class Artist:
    id: int
    name: str


@dataclass
class Album:
    id: int
    title: str
    genre: Optional[str] = None


@dataclass
class Track:
    id: int
    title: str
    artist_id: int
    album_id: Optional[int] = None
    isrc: Optional[str] = None
    duration: Optional[int] = None
    deezer_bpm: Optional[float] = None
    fetched_at: str = field(default_factory=_now)


@dataclass
class Tag:
    track_id: int
    tag: str
    source: str
    weight: float = 1.0


@dataclass
class AudioFeatures:
    track_id: int
    bpm_verified: Optional[float] = None
    bpm_confidence: Optional[float] = None
    key: Optional[str] = None
    camelot: Optional[str] = None
    energy: Optional[float] = None
    analyzer_version: int = config.ANALYZER_VERSION
    analyzed_at: str = field(default_factory=_now)
    audio_source: str = "full_mix"


@dataclass
class MatchRun:
    seed_id: int
    candidate_id: int
    total_score: float
    bpm_score: Optional[float] = None
    key_score: Optional[float] = None
    tags_score: Optional[float] = None
    genre_score: Optional[float] = None
    energy_score: Optional[float] = None
    label: Optional[str] = None
    config_version: int = config.CONFIG_VERSION
    created_at: str = field(default_factory=_now)
    run_id: Optional[int] = None


# --- Artists -------------------------------------------------------------


def upsert_artist(artist: Artist) -> None:
    sql = """
        INSERT INTO artists (id, name) VALUES (:id, :name)
        ON CONFLICT(id) DO UPDATE SET name = excluded.name
    """
    with get_connection() as conn:
        conn.execute(sql, {"id": artist.id, "name": artist.name})


def get_artist(artist_id: int) -> Optional[Artist]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM artists WHERE id = ?", (artist_id,)).fetchone()
        return Artist(id=row["id"], name=row["name"]) if row else None


# --- Albums --------------------------------------------------------------


def upsert_album(album: Album) -> None:
    sql = """
        INSERT INTO albums (id, title, genre) VALUES (:id, :title, :genre)
        ON CONFLICT(id) DO UPDATE SET title = excluded.title, genre = excluded.genre
    """
    with get_connection() as conn:
        conn.execute(sql, {"id": album.id, "title": album.title, "genre": album.genre})


def get_album(album_id: int) -> Optional[Album]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM albums WHERE id = ?", (album_id,)).fetchone()
        return Album(id=row["id"], title=row["title"], genre=row["genre"]) if row else None


# --- Tracks ----------------------------------------------------------------


def upsert_track(track: Track) -> None:
    sql = """
        INSERT INTO tracks (id, isrc, title, artist_id, album_id, duration, deezer_bpm, fetched_at)
        VALUES (:id, :isrc, :title, :artist_id, :album_id, :duration, :deezer_bpm, :fetched_at)
        ON CONFLICT(id) DO UPDATE SET
            isrc = excluded.isrc,
            title = excluded.title,
            artist_id = excluded.artist_id,
            album_id = excluded.album_id,
            duration = excluded.duration,
            deezer_bpm = excluded.deezer_bpm,
            fetched_at = excluded.fetched_at
    """
    with get_connection() as conn:
        conn.execute(
            sql,
            {
                "id": track.id,
                "isrc": track.isrc,
                "title": track.title,
                "artist_id": track.artist_id,
                "album_id": track.album_id,
                "duration": track.duration,
                "deezer_bpm": track.deezer_bpm,
                "fetched_at": track.fetched_at,
            },
        )


def get_track(track_id: int) -> Optional[Track]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
        if row is None:
            return None
        return Track(
            id=row["id"],
            isrc=row["isrc"],
            title=row["title"],
            artist_id=row["artist_id"],
            album_id=row["album_id"],
            duration=row["duration"],
            deezer_bpm=row["deezer_bpm"],
            fetched_at=row["fetched_at"],
        )


def get_track_by_isrc(isrc: str) -> Optional[Track]:
    if not isrc:
        return None
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM tracks WHERE isrc = ?", (isrc,)).fetchone()
        if row is None:
            return None
        return Track(
            id=row["id"],
            isrc=row["isrc"],
            title=row["title"],
            artist_id=row["artist_id"],
            album_id=row["album_id"],
            duration=row["duration"],
            deezer_bpm=row["deezer_bpm"],
            fetched_at=row["fetched_at"],
        )


# --- Tags ------------------------------------------------------------------


def upsert_tags(tags: list[Tag]) -> None:
    if not tags:
        return
    sql = """
        INSERT INTO tags (track_id, tag, weight, source)
        VALUES (:track_id, :tag, :weight, :source)
        ON CONFLICT(track_id, tag, source) DO UPDATE SET weight = excluded.weight
    """
    with get_connection() as conn:
        conn.executemany(
            sql,
            [
                {"track_id": t.track_id, "tag": t.tag, "weight": t.weight, "source": t.source}
                for t in tags
            ],
        )


def get_tags(track_id: int) -> list[Tag]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM tags WHERE track_id = ?", (track_id,)).fetchall()
        return [
            Tag(track_id=r["track_id"], tag=r["tag"], weight=r["weight"], source=r["source"])
            for r in rows
        ]


# --- Audio features --------------------------------------------------------


def upsert_audio_features(features: AudioFeatures) -> None:
    sql = """
        INSERT INTO audio_features
            (track_id, audio_source, bpm_verified, bpm_confidence, key, camelot, energy,
             analyzer_version, analyzed_at)
        VALUES
            (:track_id, :audio_source, :bpm_verified, :bpm_confidence, :key, :camelot, :energy,
             :analyzer_version, :analyzed_at)
        ON CONFLICT(track_id, audio_source) DO UPDATE SET
            bpm_verified = excluded.bpm_verified,
            bpm_confidence = excluded.bpm_confidence,
            key = excluded.key,
            camelot = excluded.camelot,
            energy = excluded.energy,
            analyzer_version = excluded.analyzer_version,
            analyzed_at = excluded.analyzed_at
    """
    with get_connection() as conn:
        conn.execute(
            sql,
            {
                "track_id": features.track_id,
                "audio_source": features.audio_source,
                "bpm_verified": features.bpm_verified,
                "bpm_confidence": features.bpm_confidence,
                "key": features.key,
                "camelot": features.camelot,
                "energy": features.energy,
                "analyzer_version": features.analyzer_version,
                "analyzed_at": features.analyzed_at,
            },
        )


def get_audio_features(track_id: int, audio_source: str = "full_mix") -> Optional[AudioFeatures]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM audio_features WHERE track_id = ? AND audio_source = ?",
            (track_id, audio_source),
        ).fetchone()
        if row is None:
            return None
        return AudioFeatures(
            track_id=row["track_id"],
            bpm_verified=row["bpm_verified"],
            bpm_confidence=row["bpm_confidence"],
            key=row["key"],
            camelot=row["camelot"],
            energy=row["energy"],
            analyzer_version=row["analyzer_version"],
            analyzed_at=row["analyzed_at"],
            audio_source=row["audio_source"],
        )


# --- Instrumental links (positive AND negative cache) -------------------------


@dataclass
class InstrumentalLink:
    track_id: int
    found: bool
    source: Optional[str] = None  # "deezer" | "itunes"
    source_track_id: Optional[str] = None
    title: Optional[str] = None
    artist: Optional[str] = None
    duration: Optional[int] = None
    confidence: Optional[float] = None
    checked_at: str = field(default_factory=_now)


def upsert_instrumental_link(link: InstrumentalLink) -> None:
    sql = """
        INSERT INTO instrumental_links
            (track_id, found, source, source_track_id, title, artist, duration, confidence, checked_at)
        VALUES (:track_id, :found, :source, :source_track_id, :title, :artist, :duration,
                :confidence, :checked_at)
        ON CONFLICT(track_id) DO UPDATE SET
            found = excluded.found, source = excluded.source,
            source_track_id = excluded.source_track_id, title = excluded.title,
            artist = excluded.artist, duration = excluded.duration,
            confidence = excluded.confidence, checked_at = excluded.checked_at
    """
    with get_connection() as conn:
        conn.execute(sql, {**link.__dict__, "found": 1 if link.found else 0})


def get_instrumental_link(track_id: int) -> Optional[InstrumentalLink]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM instrumental_links WHERE track_id = ?", (track_id,)
        ).fetchone()
        if row is None:
            return None
        return InstrumentalLink(
            track_id=row["track_id"],
            found=bool(row["found"]),
            source=row["source"],
            source_track_id=row["source_track_id"],
            title=row["title"],
            artist=row["artist"],
            duration=row["duration"],
            confidence=row["confidence"],
            checked_at=row["checked_at"],
        )


# --- Match runs --------------------------------------------------------------


def log_match_run(run: MatchRun) -> int:
    sql = """
        INSERT INTO match_runs
            (seed_id, candidate_id, bpm_score, key_score, tags_score, genre_score,
             energy_score, total_score, label, config_version, created_at)
        VALUES
            (:seed_id, :candidate_id, :bpm_score, :key_score, :tags_score, :genre_score,
             :energy_score, :total_score, :label, :config_version, :created_at)
    """
    with get_connection() as conn:
        cur = conn.execute(
            sql,
            {
                "seed_id": run.seed_id,
                "candidate_id": run.candidate_id,
                "bpm_score": run.bpm_score,
                "key_score": run.key_score,
                "tags_score": run.tags_score,
                "genre_score": run.genre_score,
                "energy_score": run.energy_score,
                "total_score": run.total_score,
                "label": run.label,
                "config_version": run.config_version,
                "created_at": run.created_at,
            },
        )
        return cur.lastrowid


def get_match_runs_for_seed(seed_id: int) -> list[MatchRun]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM match_runs WHERE seed_id = ? ORDER BY total_score DESC",
            (seed_id,),
        ).fetchall()
        return [
            MatchRun(
                run_id=r["run_id"],
                seed_id=r["seed_id"],
                candidate_id=r["candidate_id"],
                bpm_score=r["bpm_score"],
                key_score=r["key_score"],
                tags_score=r["tags_score"],
                genre_score=r["genre_score"],
                energy_score=r["energy_score"],
                total_score=r["total_score"],
                label=r["label"],
                config_version=r["config_version"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

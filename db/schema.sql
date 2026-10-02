-- Cue.ai database schema.
-- Primary key everywhere is the Deezer track ID (an integer, as Deezer
-- returns it). Raw API data is separated from derived analysis so that
-- re-analysis never requires refetching from an external API.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS artists (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS albums (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    genre TEXT
);

-- Deezer preview URLs are signed and expire; NEVER store them here.
-- Re-fetch a fresh preview URL by track ID when one is needed.
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY,
    isrc TEXT,
    title TEXT NOT NULL,
    artist_id INTEGER NOT NULL REFERENCES artists(id),
    album_id INTEGER REFERENCES albums(id),
    duration INTEGER,
    deezer_bpm REAL,
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tracks_artist_id ON tracks(artist_id);
CREATE INDEX IF NOT EXISTS idx_tracks_album_id ON tracks(album_id);
CREATE INDEX IF NOT EXISTS idx_tracks_isrc ON tracks(isrc);

CREATE TABLE IF NOT EXISTS tags (
    track_id INTEGER NOT NULL REFERENCES tracks(id),
    tag TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 1.0,
    source TEXT NOT NULL,
    PRIMARY KEY (track_id, tag, source)
);

CREATE INDEX IF NOT EXISTS idx_tags_track_id ON tags(track_id);

-- Keyed by (track_id, audio_source): the same song is analyzed on its
-- full-mix preview ('full_mix', used for matching scores), its official
-- instrumental ('instrumental'), and the drums+low-end beat view
-- ('beat_view'). Stores analysis only -- never audio.
CREATE TABLE IF NOT EXISTS audio_features (
    track_id INTEGER NOT NULL REFERENCES tracks(id),
    audio_source TEXT NOT NULL DEFAULT 'full_mix',
    bpm_verified REAL,
    bpm_confidence REAL,
    key TEXT,
    camelot TEXT,
    energy REAL,
    analyzer_version INTEGER NOT NULL,
    analyzed_at TEXT NOT NULL,
    PRIMARY KEY (track_id, audio_source)
);

-- Cache of official-instrumental lookups, INCLUDING negative results
-- (found = 0) so we don't re-hit Deezer/iTunes for songs that have none.
CREATE TABLE IF NOT EXISTS instrumental_links (
    track_id INTEGER PRIMARY KEY REFERENCES tracks(id),
    found INTEGER NOT NULL,
    source TEXT,
    source_track_id TEXT,
    title TEXT,
    artist TEXT,
    duration INTEGER,
    confidence REAL,
    checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS match_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    seed_id INTEGER NOT NULL REFERENCES tracks(id),
    candidate_id INTEGER NOT NULL REFERENCES tracks(id),
    bpm_score REAL,
    key_score REAL,
    tags_score REAL,
    genre_score REAL,
    energy_score REAL,
    total_score REAL NOT NULL,
    label TEXT,
    config_version INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_match_runs_seed_id ON match_runs(seed_id);

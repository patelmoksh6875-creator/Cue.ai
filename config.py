"""Central configuration: weights, thresholds, versions, API keys.

Nothing outside this file should hardcode a tuning constant, a model name,
or read an env var for an API key. Change behavior here, not in the modules
that use it.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# --- Paths -------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "cue.sqlite3"

# --- API keys ------------------------------------------------------------
LASTFM_API_KEY = os.getenv("LASTFM_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# --- API endpoints ---------------------------------------------------------
DEEZER_BASE_URL = "https://api.deezer.com"
LASTFM_BASE_URL = "https://ws.audioscrobbler.com/2.0/"

# --- Rate limiting -------------------------------------------------------
# Deezer documents roughly 50 requests / 5 seconds per IP.
DEEZER_MAX_REQUESTS = 50
DEEZER_PER_SECONDS = 5.0

# Last.fm has no hard published cap for this key tier; stay well under
# anything that would look like abuse.
LASTFM_MAX_REQUESTS = 5
LASTFM_PER_SECONDS = 1.0

# --- Matching output -------------------------------------------------------
RESULT_COUNT = 20

# The server returns this many scored/diversified results (sorted by
# score) so the UI's artist/genre filter bar can refill from the pool
# client-side instead of leaving a handful of results after filtering.
# The UI still only *shows* RESULT_COUNT at a time, pre-filter.
RESULT_POOL = 60

# Candidate pool must be much bigger than RESULT_COUNT since hard filters
# remove most of it.
CANDIDATE_POOL_TARGET_MIN = 100
CANDIDATE_POOL_TARGET_MAX = 200

# --- Hard filter thresholds -------------------------------------------------
# BPM tolerance as a fraction of the seed BPM (0.06 == +/-6%).
BPM_TOLERANCE_PCT = 0.06
# Also match half-time / double-time relationships within the same tolerance.
BPM_HALF_DOUBLE_MATCHING = True

# --- Scoring weights -------------------------------------------------------
# Must sum to 1.0 (tests/test_scoring.py enforces this) so total_score is a
# true 0..1 value, shown in the UI as a percent match. matching/scoring.py
# separately renormalizes over whatever components are actually available
# for a given track (e.g. no tags), so a missing component doesn't also
# need the remaining weights to sum to 1 on their own.
SCORE_WEIGHTS = {
    "bpm": 0.30,
    "key": 0.25,
    "tags": 0.20,
    "genre": 0.15,
    "energy": 0.10,
}

# Camelot-wheel key compatibility scores by "steps away" on the wheel.
# 0 = identical key, 1 = adjacent (perfect mix), 2 = two steps, etc.
CAMELOT_COMPATIBILITY_BY_DISTANCE = {
    0: 1.0,   # same key
    1: 0.85,  # adjacent number or relative major/minor (same number, other letter)
    2: 0.4,
    3: 0.15,
}
CAMELOT_DEFAULT_SCORE = 0.0  # anything farther away

# --- Diversity rule --------------------------------------------------------
MAX_TRACKS_PER_ARTIST = 2

# --- Safe vs adventurous labeling ------------------------------------------
# A result is "safe" when both BPM and key scores clear these floors.
SAFE_BPM_SCORE_MIN = 0.85
SAFE_KEY_SCORE_MIN = 0.85

# --- Audio analysis ----------------------------------------------------
ANALYZER_VERSION = 1
PREVIEW_SAMPLE_RATE = 22050  # librosa default; keep explicit for reproducibility

# --- Config version (bump whenever SCORE_WEIGHTS or thresholds change) ----
CONFIG_VERSION = 1

# --- Groq models -----------------------------------------------------------
# Ordered fallback chain: primary -> fallback -> cheap. Never hardcode a
# model name anywhere outside this file.
GROQ_MODEL_PRIMARY = "openai/gpt-oss-120b"
GROQ_MODEL_FALLBACK = "llama-3.3-70b-versatile"
GROQ_MODEL_CHEAP = "llama-3.1-8b-instant"
GROQ_MODELS_ORDERED = [GROQ_MODEL_PRIMARY, GROQ_MODEL_FALLBACK]

# Groq is optional. When False (or no key set), the pipeline runs fully
# deterministic with templated explanations.
GROQ_ENABLED = bool(GROQ_API_KEY)

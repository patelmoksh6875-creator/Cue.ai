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
ANALYZER_VERSION = 2  # 2: audio_features keyed by (track_id, audio_source)
PREVIEW_SAMPLE_RATE = 22050  # librosa default; keep explicit for reproducibility

# --- Config version (bump whenever SCORE_WEIGHTS or thresholds change) ----
CONFIG_VERSION = 1

# --- Groq models -----------------------------------------------------------
# Ordered fallback chain: primary -> fallback -> cheap. Never hardcode a
# model name anywhere outside this file.
# llama-3.3-70b-versatile and llama-3.1-8b-instant (the originally chosen
# fallback/cheap models) were removed from Groq's lineup entirely -- see
# GROQ_MODELS_ORDERED's live-availability check in agent/groq_agent.py,
# which is exactly what caught this. Replaced with the current smaller
# gpt-oss tier; verified against `client.models.list()` on 2026-09-30.
GROQ_MODEL_PRIMARY = "openai/gpt-oss-120b"
GROQ_MODEL_FALLBACK = "openai/gpt-oss-20b"
GROQ_MODEL_CHEAP = "openai/gpt-oss-20b"
GROQ_MODELS_ORDERED = [GROQ_MODEL_PRIMARY, GROQ_MODEL_FALLBACK]

# Groq is optional. When False (or no key set), the pipeline runs fully
# deterministic with templated explanations.
GROQ_ENABLED = bool(GROQ_API_KEY)

# --- Instrumental lookup (V4) --------------------------------------------------
ITUNES_BASE_URL = "https://itunes.apple.com"
ITUNES_MAX_REQUESTS = 15      # iTunes Search soft limit is ~20/min; stay under it
ITUNES_PER_SECONDS = 60.0
# An instrumental must run about as long as the original (seconds).
INSTRUMENTAL_DURATION_TOLERANCE_S = 12
# Below this confidence a candidate is treated as "none found".
INSTRUMENTAL_MIN_CONFIDENCE = 0.75
# Negative results (no instrumental exists) are re-checked after this long.
INSTRUMENTAL_NEGATIVE_TTL_DAYS = 30

# --- Beat view fallback (drums + low end, no ML) ---------------------------------
# Mix the original's low end (below BEATVIEW_LOW_END_HZ) back in so kick and
# 808/bass are present. Trap-style beats lean on that low end. Change by
# listening; see README "Beat view".
BEATVIEW_ADD_LOW_END = True
BEATVIEW_LOW_END_HZ = 150  # widened from 120 to match the mix crossover
BEATVIEW_HPSS_MARGIN = 3.0

# --- Mix snippet window search ---------------------------------------------------
MIX_WINDOW_CANDIDATES = 3
MIX_BLEND_BEATS_LONG = 16
MIX_BLEND_BEATS_SHORT = 8

# --- Preview mix render (V4 fix) ---------------------------------------------------
# Render everything at one common rate/channel layout. 22.05 kHz audio is for
# ANALYSIS only (beats/tempo/key/windows); rendering at it capped the mix at 11 kHz.
RENDER_SAMPLE_RATE = 44100
MIX_RENDER_VERSION = 2            # bump to invalidate cached snippets after render changes
MIX_OVERLAP_BEAT_OPTIONS = (16, 8, 4)   # largest that fits (overlap <= length - 2 * MIX_MIN_SOLO_S)
MIX_MIN_SOLO_S = 2.0              # at least this much of A alone, and of B alone
MIX_TARGET_RMS_DBFS = -18.0       # both clips are matched to this before mixing
MIX_PEAK_CEILING_DBFS = -1.0      # final limiter target
MIX_BASS_CROSSOVER_HZ = 150
MIX_BASS_SWAP_WINDOW = (0.4, 0.6)  # overlap position where the low end hands over
# Beat view fullness: optional gentle broadband copy of the original (0 = off).
# Higher = fuller but lets more vocal through. Choose by ear.
BEATVIEW_BROADBAND_MIX = 0.0

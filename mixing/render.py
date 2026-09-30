"""Mix snippet orchestration: fetch previews, reuse/compute analysis,
tempo-match, beat-align, render a transition, export MP3, cache by
(a_id, b_id, style, length, analyzer_version).

Hard constraint (tell the user, always): the only audio available is
Deezer's 30-second preview clips, taken from somewhere in the song, not
the actual intro/outro -- so this shows how two songs sound together,
not the exact real-track transition point. See
CLAUDE_HANDOFF_V2_WEB_UI.md Section 6.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import librosa
import numpy as np
import soundfile as sf

import config
from analysis import audio
from db import repo
from matching.scoring import camelot_distance
from mixing import align
from mixing.styles import STYLES
from sources import deezer

SNIPPET_DIR = Path(__file__).resolve().parent.parent / "logs" / "snippets"
MIN_CONFIDENCE_TO_REUSE = 0.3
DEFAULT_LENGTH_S = 12
MIN_LENGTH_S = 10
MAX_LENGTH_S = 15


class MixError(Exception):
    pass


@dataclass
class MixWarnings:
    stretch_exceeds_quality: bool
    stretch_pct: float
    key_incompatible: bool
    low_confidence_bpm: bool


@dataclass
class MixResult:
    path: Path
    warnings: MixWarnings


def snippet_cache_key(a_id: int, b_id: int, style: str, length_seconds: int) -> str:
    return f"{a_id}_{b_id}_{style}_{length_seconds}_{config.ANALYZER_VERSION}"


def snippet_path(cache_key: str) -> Path:
    return SNIPPET_DIR / f"{cache_key}.mp3"


def _get_or_analyze(track_id: int, preview_url: str, deezer_bpm: Optional[float]):
    cached = repo.get_audio_features(track_id)
    if (
        cached is not None
        and cached.analyzer_version == config.ANALYZER_VERSION
        and cached.bpm_confidence is not None
        and cached.bpm_confidence >= MIN_CONFIDENCE_TO_REUSE
    ):
        return cached
    result = audio.analyze_preview(preview_url, deezer_bpm=deezer_bpm)
    features = repo.AudioFeatures(
        track_id=track_id,
        bpm_verified=result.bpm,
        bpm_confidence=result.bpm_confidence,
        key=result.key,
        camelot=result.camelot,
        energy=result.energy,
    )
    repo.upsert_audio_features(features)
    return features


def _load_audio(preview_url: str) -> tuple[np.ndarray, int]:
    tmp_path = audio.download_preview(preview_url)
    try:
        y, sr = librosa.load(str(tmp_path), sr=config.PREVIEW_SAMPLE_RATE, mono=True)
        return y, sr
    finally:
        tmp_path.unlink(missing_ok=True)


def _take_segment(y: np.ndarray, sr: int, start_s: float, length_s: float) -> np.ndarray:
    start = max(0, int(start_s * sr))
    end = min(len(y), start + int(length_s * sr))
    segment = y[start:end]
    needed = int(length_s * sr)
    if len(segment) < needed:
        segment = np.pad(segment, (0, needed - len(segment)))
    return segment


def _key_incompatible(camelot_a: Optional[str], camelot_b: Optional[str]) -> bool:
    if not camelot_a or not camelot_b:
        return False
    distance = camelot_distance(camelot_a, camelot_b)
    return distance is not None and distance > 1


def _export_mp3(y: np.ndarray, sr: int, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
        wav_path = Path(tmp_wav.name)
    try:
        sf.write(str(wav_path), y, sr)
        if shutil.which("ffmpeg") is None:
            raise MixError("ffmpeg not found on PATH -- needed to export the snippet as MP3")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), str(out_path)],
            check=True,
        )
    finally:
        wav_path.unlink(missing_ok=True)


def build_snippet(
    a_id: int, b_id: int, style: str = "blend", length_seconds: int = DEFAULT_LENGTH_S
) -> MixResult:
    if style not in STYLES:
        raise MixError(f"Unknown style '{style}'. Choose one of: {', '.join(STYLES)}")
    length_seconds = max(MIN_LENGTH_S, min(MAX_LENGTH_S, length_seconds))

    cache_key = snippet_cache_key(a_id, b_id, style, length_seconds)
    out_path = snippet_path(cache_key)

    track_a = deezer.get_track_detail(a_id)
    track_b = deezer.get_track_detail(b_id)
    preview_a = deezer.get_fresh_preview_url(a_id)
    preview_b = deezer.get_fresh_preview_url(b_id)
    if not preview_a or not preview_b:
        raise MixError("No preview available for one or both tracks in this region")

    features_a = _get_or_analyze(a_id, preview_a, track_a.bpm)
    features_b = _get_or_analyze(b_id, preview_b, track_b.bpm)
    if not features_a.bpm_verified or not features_b.bpm_verified:
        raise MixError("Could not determine BPM for one or both tracks")

    warnings = MixWarnings(
        stretch_exceeds_quality=False,
        stretch_pct=0.0,
        key_incompatible=_key_incompatible(features_a.camelot, features_b.camelot),
        low_confidence_bpm=(
            (features_a.bpm_confidence or 0) < MIN_CONFIDENCE_TO_REUSE
            or (features_b.bpm_confidence or 0) < MIN_CONFIDENCE_TO_REUSE
        ),
    )

    if out_path.exists():
        return MixResult(path=out_path, warnings=warnings)

    y_a, sr = _load_audio(preview_a)
    y_b, sr_b = _load_audio(preview_b)
    if sr_b != sr:
        y_b = librosa.resample(y_b, orig_sr=sr_b, target_sr=sr)

    tempo_plan = align.plan_tempo_match(features_a.bpm_verified, features_b.bpm_verified)
    warnings.stretch_exceeds_quality = tempo_plan.exceeds_quality_threshold
    warnings.stretch_pct = round(tempo_plan.stretch_pct, 3)

    y_b_stretched = align.time_stretch(y_b, tempo_plan.stretch_ratio)

    beats_b = librosa.beat.beat_track(y=y_b_stretched, sr=sr, units="time")[1]
    offset = align.best_beat_offset(y_a, y_b_stretched, sr, np.asarray(beats_b))

    lead_s = length_seconds * 0.25
    blend_s = length_seconds * 0.5
    tail_s = length_seconds - lead_s - blend_s

    # Pull segments from a bit into each preview, away from the very
    # start/end where previews often fade in/out -- still an arbitrary
    # slice of a 30s clip, not the song's real intro/outro.
    a_start = min(8.0, max(0.0, len(y_a) / sr - (lead_s + blend_s) - 1))
    a_region = _take_segment(y_a, sr, a_start, lead_s + blend_s)

    b_start = offset
    b_region = _take_segment(y_b_stretched, sr, b_start, blend_s + tail_s)

    a_lead = a_region[: int(lead_s * sr)]
    a_tail = a_region[int(lead_s * sr) :]
    b_tail_part = b_region[int(blend_s * sr) :]
    b_blend_part = b_region[: int(blend_s * sr)]

    transition = STYLES[style](a_tail, b_blend_part, sr)
    full = np.concatenate([a_lead, transition, b_tail_part]).astype(np.float32)

    peak = np.max(np.abs(full)) or 1.0
    if peak > 0.98:
        full = full / peak * 0.98

    _export_mp3(full, sr, out_path)
    return MixResult(path=out_path, warnings=warnings)


def cleanup_snippet_cache() -> int:
    """Personal use only -- don't build a persistent library of derived
    preview audio. Called on server shutdown (and can be run on a
    schedule); returns how many files were removed."""
    if not SNIPPET_DIR.exists():
        return 0
    removed = 0
    for f in SNIPPET_DIR.glob("*.mp3"):
        f.unlink(missing_ok=True)
        removed += 1
    return removed

"""Mix snippet orchestration (V4): choose each song's audio source, analyze
the CHOSEN audio, tempo-match, pick the best windows, beat-align, render a
whole-beats transition, export MP3, cache.

Audio source per song (the normal results players are untouched and keep
playing the real song):
    official instrumental  ->  beat view (drums + low end)  ->  full mix

HARD LIMITS (shown in the UI and README, never hidden):
  * Deezer/iTunes previews are ~30 s clips from a position we cannot choose.
    An instrumental or beat view of the same window is still that window --
    it makes the beat clearer, it does NOT fix "wrong section of the song"
    (e.g. a beat switch the clip happens to miss).
  * Official instrumentals don't exist for every song.
  * The beat view is thin (no melody) and leaks some vocal transients.
  * Preview audio is temp only, personal analysis; the snippet cache is
    wiped on shutdown. Nothing is stored but analysis numbers and links.

Possible future upgrade (NOT built): the user drags in two full audio
files for one pair; we analyze the tempo map/sections, match sections,
delete the audio and cache only the analysis. Nothing here blocks that --
build_snippet() only needs (audio array, sr, analysis) per song.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import librosa
import numpy as np
import soundfile as sf

import config
from analysis import audio
from db import repo
from matching import instrumentals
from matching.scoring import camelot_distance
from mixing import align, beatview, windows
from mixing.styles import STYLES
from sources import deezer

SNIPPET_DIR = Path(__file__).resolve().parent.parent / "logs" / "snippets"
MIN_CONFIDENCE_TO_REUSE = 0.3
DEFAULT_LENGTH_S = 12
MIN_LENGTH_S = 10
MAX_LENGTH_S = 15
SOURCES = ("auto", "instrumental", "beat_view", "full_mix")

LIMITATION_NOTE = (
    "Built from 30-second previews. This shows how the beats blend, not where "
    "to transition in the full songs."
)
SOURCE_LABELS = {
    "instrumental": "Instrumental",
    "beat_view": "Beat view: drums and low end (thin, some vocal leakage)",
    "full_mix": "Full mix",
}


class MixError(Exception):
    pass


@dataclass
class MixWarnings:
    stretch_exceeds_quality: bool = False
    stretch_pct: float = 0.0
    key_incompatible: bool = False
    low_confidence_bpm: bool = False
    feel_mismatch: bool = False
    tempo_change_in_clip: bool = False
    messages: list[str] = field(default_factory=list)


@dataclass
class MixResult:
    path: Path
    warnings: MixWarnings
    info: dict


@dataclass
class SourceAudio:
    label: str                       # instrumental | beat_view | full_mix
    y: np.ndarray
    instrumental: Optional[repo.InstrumentalLink] = None


def snippet_cache_key(
    a_id: int, b_id: int, style: str, length_seconds: int,
    source: str = "auto", window_rank: int = 0,
) -> str:
    return f"{a_id}_{b_id}_{style}_{length_seconds}_{source}_w{window_rank}_{config.ANALYZER_VERSION}"


def snippet_path(cache_key: str) -> Path:
    return SNIPPET_DIR / f"{cache_key}.mp3"


def _info_path(cache_key: str) -> Path:
    return SNIPPET_DIR / f"{cache_key}.json"


def load_cached_info(cache_key: str) -> Optional[dict]:
    p = _info_path(cache_key)
    if snippet_path(cache_key).exists() and p.exists():
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            return None
    return None


def _load_audio(preview_url: str) -> tuple[np.ndarray, int]:
    """Download and decode via ffmpeg to mono wav (handles mp3 AND iTunes m4a)."""
    src = audio.download_preview(preview_url)
    wav = Path(tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-ac", "1",
             "-ar", str(config.PREVIEW_SAMPLE_RATE), str(wav)],
            check=True,
        )
        y, sr = sf.read(str(wav), dtype="float32")
        return y, int(sr)
    except (subprocess.CalledProcessError, FileNotFoundError, RuntimeError) as exc:
        raise MixError(f"Could not decode preview audio: {exc}") from exc
    finally:
        src.unlink(missing_ok=True)
        wav.unlink(missing_ok=True)


def _analysis_for(track_id: int, source: str, y: np.ndarray, sr: int, deezer_bpm: Optional[float]):
    """Cached analysis for (track, audio_source); re-analyzed on version bump
    or low confidence. Matching scores keep using the 'full_mix' rows."""
    cached = repo.get_audio_features(track_id, source)
    if (
        cached is not None
        and cached.analyzer_version == config.ANALYZER_VERSION
        and cached.bpm_confidence is not None
        and cached.bpm_confidence >= MIN_CONFIDENCE_TO_REUSE
    ):
        return cached
    result = audio.analyze_samples(y, sr, deezer_bpm)
    features = repo.AudioFeatures(
        track_id=track_id, audio_source=source, bpm_verified=result.bpm,
        bpm_confidence=result.bpm_confidence, key=result.key,
        camelot=result.camelot, energy=result.energy,
    )
    repo.upsert_audio_features(features)
    return features


def choose_source_order(requested: str) -> list[str]:
    """Sources to try, in order, for a requested mode. 'auto' is the V4
    default order: instrumental -> beat view -> full mix."""
    if requested == "full_mix":
        return ["full_mix"]
    if requested == "beat_view":
        return ["beat_view", "full_mix"]
    return ["instrumental", "beat_view", "full_mix"]  # auto / instrumental


def resolve_source(
    track: deezer.DeezerTrack, y_full: np.ndarray, sr: int, requested: str
) -> SourceAudio:
    for label in choose_source_order(requested):
        if label == "instrumental":
            try:
                link = instrumentals.find_instrumental(track)
                url = instrumentals.instrumental_preview_url(link) if link else None
                if link and url:
                    y, _ = _load_audio(url)
                    return SourceAudio("instrumental", y, link)
            except Exception:  # lookup/decode trouble must not break the mix
                continue
        elif label == "beat_view":
            try:
                return SourceAudio("beat_view", beatview.make_beat_view(y_full, sr))
            except Exception:
                continue
        else:
            return SourceAudio("full_mix", y_full)
    return SourceAudio("full_mix", y_full)


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


def blend_beats_for(bpm: float, length_seconds: int) -> int:
    """Whole number of beats for the transition: 16 (or 8) when it fits in
    ~60% of the snippet, else the largest of 8/4 that does."""
    beat_s = 60.0 / bpm
    for beats in (config.MIX_BLEND_BEATS_LONG, config.MIX_BLEND_BEATS_SHORT, 4):
        if beats * beat_s <= length_seconds * 0.6:
            return beats
    return 4


def _half_tempo_drift(beats: np.ndarray) -> float:
    """Relative difference between first-half and second-half beat spacing."""
    if len(beats) < 8:
        return 0.0
    iv = np.diff(beats)
    h = len(iv) // 2
    a, b = float(np.median(iv[:h])), float(np.median(iv[h:]))
    return abs(a - b) / max(a, b)


def _grid_overlap(beats_x: np.ndarray, beats_y: np.ndarray, tol: float = 0.06) -> float:
    if len(beats_x) == 0 or len(beats_y) == 0:
        return 0.0
    hits = sum(1 for t in beats_x if np.min(np.abs(beats_y - t)) <= tol)
    return hits / len(beats_x)


def _song_report(track, src: SourceAudio, full_feat, chosen_feat, grid_overlap: float) -> dict:
    bpm_full, bpm_chosen = full_feat.bpm_verified, chosen_feat.bpm_verified
    ratio = bpm_chosen / bpm_full if bpm_full else 1.0
    return {
        "id": track.id, "title": track.title, "artist": track.artist_name,
        "source": src.label, "source_label": SOURCE_LABELS[src.label],
        "instrumental": (
            {"title": src.instrumental.title, "artist": src.instrumental.artist,
             "from": src.instrumental.source, "confidence": src.instrumental.confidence}
            if src.instrumental else None
        ),
        "bpm_full_mix": round(bpm_full, 1), "bpm_chosen": round(bpm_chosen, 1),
        "bpm_confidence_chosen": round(chosen_feat.bpm_confidence or 0, 2),
        "bpm_changed": abs(ratio - 1.0) > 0.03,
        "beat_grid_overlap_with_full_mix": round(grid_overlap, 2),
        "beat_grid_changed": src.label != "full_mix" and grid_overlap < 0.7,
    }


def build_snippet(
    a_id: int, b_id: int, style: str = "blend", length_seconds: int = DEFAULT_LENGTH_S,
    source: str = "auto", window_rank: int = 0,
) -> MixResult:
    if style not in STYLES:
        raise MixError(f"Unknown style '{style}'. Choose one of: {', '.join(STYLES)}")
    if source not in SOURCES:
        raise MixError(f"Unknown source '{source}'. Choose one of: {', '.join(SOURCES)}")
    length_seconds = max(MIN_LENGTH_S, min(MAX_LENGTH_S, length_seconds))
    window_rank = max(0, window_rank)

    cache_key = snippet_cache_key(a_id, b_id, style, length_seconds, source, window_rank)
    track_a = deezer.get_track_detail(a_id)
    track_b = deezer.get_track_detail(b_id)
    url_a = deezer.get_fresh_preview_url(a_id)
    url_b = deezer.get_fresh_preview_url(b_id)
    if not url_a or not url_b:
        raise MixError("No preview available for one or both tracks in this region")

    y_full_a, sr = _load_audio(url_a)
    y_full_b, _ = _load_audio(url_b)
    src_a = resolve_source(track_a, y_full_a, sr, source)
    src_b = resolve_source(track_b, y_full_b, sr, source)

    full_a = _analysis_for(a_id, "full_mix", y_full_a, sr, track_a.bpm)
    full_b = _analysis_for(b_id, "full_mix", y_full_b, sr, track_b.bpm)
    ch_a = full_a if src_a.label == "full_mix" else _analysis_for(a_id, src_a.label, src_a.y, sr, None)
    ch_b = full_b if src_b.label == "full_mix" else _analysis_for(b_id, src_b.label, src_b.y, sr, None)
    if not ch_a.bpm_verified or not ch_b.bpm_verified:
        raise MixError("Could not determine BPM for one or both tracks")

    # Alignment uses the CHOSEN audio's analysis (cleaner on instrumentals);
    # matching scores elsewhere keep using the full-mix analysis.
    plan = align.plan_tempo_match(ch_a.bpm_verified, ch_b.bpm_verified)
    y_a = src_a.y
    y_b = align.time_stretch(src_b.y, plan.stretch_ratio)
    bpm = ch_a.bpm_verified
    beats_a = np.asarray(librosa.beat.beat_track(y=y_a, sr=sr, units="time", start_bpm=bpm)[1])
    beats_b = np.asarray(librosa.beat.beat_track(y=y_b, sr=sr, units="time", start_bpm=bpm)[1])
    full_beats_a = np.asarray(librosa.beat.beat_track(y=y_full_a, sr=sr, units="time")[1])
    # Grid-change report compares UNSTRETCHED beats of chosen vs full-mix audio.
    full_beats_b = np.asarray(librosa.beat.beat_track(y=y_full_b, sr=sr, units="time")[1])
    raw_beats_b = np.asarray(librosa.beat.beat_track(y=src_b.y, sr=sr, units="time", start_bpm=ch_b.bpm_verified)[1])

    n_beats = blend_beats_for(bpm, length_seconds)
    blend_s = n_beats * 60.0 / bpm
    lead_s = max(1.0, (length_seconds - blend_s) * 0.45)
    tail_s = max(1.0, length_seconds - blend_s - lead_s)

    cands = windows.rank_windows(
        y_a, y_b, sr, beats_a, beats_b, blend_s, lead_s, tail_s, bpm,
        top=config.MIX_WINDOW_CANDIDATES,
    )
    if not cands:
        raise MixError("The previews are too short to find a window for this blend length")
    rank = min(window_rank, len(cands) - 1)
    chosen = cands[rank]

    a_region = _take_segment(y_a, sr, chosen.a_blend_start - lead_s, lead_s + blend_s)
    b_region = _take_segment(y_b, sr, chosen.b_blend_start, blend_s + tail_s)
    a_lead, a_blend = a_region[: int(lead_s * sr)], a_region[int(lead_s * sr):]
    b_blend, b_tail = b_region[: int(blend_s * sr)], b_region[int(blend_s * sr):]

    transition = STYLES[style](a_blend, b_blend, sr)
    full = np.concatenate([a_lead, transition, b_tail]).astype(np.float32)
    peak = float(np.max(np.abs(full))) or 1.0
    if peak > 0.98:
        full = full / peak * 0.98

    # ---- warnings, in plain language -------------------------------------
    w = MixWarnings(stretch_pct=round(plan.stretch_pct, 3), stretch_exceeds_quality=plan.exceeds_quality_threshold)
    w.key_incompatible = _key_incompatible(ch_a.camelot, ch_b.camelot)
    w.low_confidence_bpm = min(ch_a.bpm_confidence or 0, ch_b.bpm_confidence or 0) < MIN_CONFIDENCE_TO_REUSE
    drift = max(_half_tempo_drift(beats_a), _half_tempo_drift(beats_b))
    w.tempo_change_in_clip = drift > 0.08
    w.feel_mismatch = plan.used_half_double or chosen.density_match < 0.6
    if w.stretch_exceeds_quality:
        w.messages.append(f"The second song was stretched {plan.stretch_pct:.0%} to match tempo; quality may suffer.")
    if w.key_incompatible:
        w.messages.append("The keys are not close on the Camelot wheel; expect some clash.")
    if w.low_confidence_bpm:
        w.messages.append("Low confidence in one song's tempo; the blend may sound off-grid even for a good pair.")
    if w.tempo_change_in_clip:
        w.messages.append("The tempo seems to change inside a clip (possible beat switch); the preview may be a different section than you expect.")
    if w.feel_mismatch:
        w.messages.append("The two clips may have different feels (half-time vs double-time, or very different drum density).")
    if chosen.drum_corr < 0.25:
        w.messages.append("The kick patterns don't line up well in the best window found.")
    for s in (src_a, src_b):
        if s.label == "beat_view":
            w.messages.append("Beat view is thin (drums and low end only) and may leak some vocal consonants.")
            break

    _export_mp3(full, sr, snippet_path(cache_key))
    info = {
        "requested_source": source,
        "a": _song_report(track_a, src_a, full_a, ch_a, _grid_overlap(beats_a, full_beats_a)),
        "b": _song_report(track_b, src_b, full_b, ch_b, _grid_overlap(raw_beats_b, full_beats_b)),
        "windows": [
            {"rank": i, "a_start": round(c.a_blend_start, 1), "b_start": round(c.b_blend_start, 1),
             "score": round(c.score, 3), "drum_corr": round(c.drum_corr, 2)}
            for i, c in enumerate(cands)
        ],
        "window_rank": rank,
        "blend_beats": n_beats,
        "alignment": {"kick_corr": round(chosen.drum_corr, 2), "well_aligned": chosen.drum_corr >= 0.25},
        "warnings": {**{k: v for k, v in w.__dict__.items() if k != "messages"}, "messages": w.messages},
        "note": LIMITATION_NOTE,
    }
    _info_path(cache_key).write_text(json.dumps(info))
    return MixResult(path=snippet_path(cache_key), warnings=w, info=info)


def cleanup_snippet_cache() -> int:
    """Personal use only -- don't build a persistent library of derived
    preview audio. Called on server shutdown; returns files removed."""
    if not SNIPPET_DIR.exists():
        return 0
    removed = 0
    for f in list(SNIPPET_DIR.glob("*.mp3")) + list(SNIPPET_DIR.glob("*.json")):
        f.unlink(missing_ok=True)
        removed += 1
    return removed

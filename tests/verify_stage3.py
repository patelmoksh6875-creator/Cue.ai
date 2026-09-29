"""Manual verification script for Stage 3 (not a pytest file).

Run: python tests/verify_stage3.py

Analyzes ~20 songs whose real-world BPM is well documented, compares
librosa's verified BPM against that ground truth (and against Deezer's own
BPM field when Deezer has one), stores results in audio_features, and
prints the disagreement rate honestly -- including half/double-time cases.
"""
from __future__ import annotations

from db import repo
from sources import deezer
from analysis import audio

# (search query, commonly-documented real BPM)
KNOWN_SONGS = [
    ("One More Time Daft Punk", 123),
    ("Get Lucky Daft Punk", 116),
    ("Around the World Daft Punk", 121),
    ("Billie Jean Michael Jackson", 117),
    ("Blinding Lights The Weeknd", 171),
    ("Uptown Funk Bruno Mars", 115),
    ("Levels Avicii", 126),
    ("One Swedish House Mafia", 128),
    ("Clarity Zedd", 128),
    ("Titanium David Guetta", 126),
    ("Sandstorm Darude", 136),
    ("Firestarter The Prodigy", 137),
    ("Sweet Dreams Eurythmics", 125),
    ("Take On Me a-ha", 169),
    ("Bad Guy Billie Eilish", 135),
    ("Rolling in the Deep Adele", 105),
    ("Shape of You Ed Sheeran", 96),
    ("Feel Good Inc Gorillaz", 138),
    ("Sweet Child O Mine Guns N Roses", 125),
    ("Don't Stop Believin Journey", 119),
]


def _within_tolerance(a: float, b: float, pct: float = 0.06) -> bool:
    return abs(a - b) / b <= pct


def _is_half_double(a: float, b: float) -> bool:
    ratio = a / b
    return (0.47 <= ratio <= 0.53) or (1.9 <= ratio <= 2.1)


def main() -> None:
    repo.init_db()
    correct = 0
    half_double = 0
    wrong = 0
    total = 0
    rows = []

    for query, known_bpm in KNOWN_SONGS:
        results = deezer.search_tracks(query, limit=1)
        if not results:
            print(f"[skip] no Deezer match for: {query}")
            continue
        hit = results[0]
        detail = deezer.get_track_detail(hit.id)
        preview_url = deezer.get_fresh_preview_url(hit.id)
        if not preview_url:
            print(f"[skip] no preview available for: {query}")
            continue

        try:
            result = audio.analyze_preview(preview_url, deezer_bpm=detail.bpm)
        except Exception as exc:  # decoding can legitimately fail on bad previews
            print(f"[error] analysis failed for {query}: {exc}")
            continue

        repo.upsert_audio_features(
            repo.AudioFeatures(
                track_id=hit.id,
                bpm_verified=result.bpm,
                bpm_confidence=result.bpm_confidence,
                key=result.key,
                camelot=result.camelot,
                energy=result.energy,
            )
        )

        total += 1
        verdict = "MATCH"
        if _within_tolerance(result.bpm, known_bpm):
            correct += 1
        elif _is_half_double(result.bpm, known_bpm):
            half_double += 1
            verdict = "HALF/DOUBLE"
        else:
            wrong += 1
            verdict = "MISMATCH"

        rows.append(
            (query, known_bpm, detail.bpm, round(result.bpm, 1), result.camelot, verdict)
        )

    print(f"\n{'song':<34}{'known':>7}{'deezer':>8}{'librosa':>9}{'camelot':>9}  verdict")
    for query, known_bpm, deezer_bpm, verified_bpm, camelot, verdict in rows:
        deezer_str = f"{deezer_bpm:.0f}" if deezer_bpm else "-"
        print(f"{query:<34}{known_bpm:>7}{deezer_str:>8}{verified_bpm:>9}{camelot:>9}  {verdict}")

    print(f"\nTotal analyzed: {total}")
    if total:
        print(f"Within +/-6% tolerance: {correct} ({correct / total:.0%})")
        print(f"Half/double-time: {half_double} ({half_double / total:.0%})")
        print(f"Mismatched: {wrong} ({wrong / total:.0%})")
    print("\nStage 3 verification complete (accuracy reported above, not claimed).")


if __name__ == "__main__":
    main()

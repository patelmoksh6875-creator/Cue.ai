"""Debug a Preview mix: python -m mixing.debug <a_id> <b_id> [style] [source]

Writes one WAV per pipeline stage per song to a temp directory and prints
a metrics table (sample rate, channels, duration, RMS, peak, spectral
centroid, share of energy above 4 kHz) plus the render settings. Temp audio
only -- personal analysis; delete the directory when done.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import soundfile as sf

from db import repo
from mixing import metrics, render


def run(a_id: int, b_id: int, style: str = "blend", source: str = "auto", out_dir: Path | None = None) -> dict:
    repo.init_db()
    out = out_dir or Path(tempfile.mkdtemp(prefix="cue_mixdebug_"))
    rows: list[dict] = []
    settings: dict = {}

    def trace(stage, who, y, sr, extra):
        name = f"{stage.split(' ')[0]}_{who}.wav"
        sf.write(str(out / name), y, sr)
        row = {"stage": stage, "who": who, **metrics.describe(y, sr)}
        for k in ("stretch_ratio", "audio_source", "instrumental"):
            if k in extra:
                row[k] = extra[k]
        rows.append(row)
        if stage.startswith("7"):
            settings.update(extra)

    result = render.build_snippet(a_id, b_id, style, 12, source, 0, trace=trace)
    print(f"\nWAVs: {out}\n")
    print(f"{'stage':62}{'song':5}{'sr':>6}{'ch':>3}{'dur':>6}{'RMS':>7}{'peak':>7}{'cent Hz':>8}{'HF>4k':>7}")
    for r in rows:
        print(f"{r['stage'][:61]:62}{r['who']:5}{r['sr']:>6}{r['channels']:>3}{r['duration_s']:>6}"
              f"{r['rms_dbfs']:>7}{r['peak_dbfs']:>7}{r['centroid_hz']:>8}{r['hf_share']:>7}")
    print("\nsources:", {r["who"]: (r.get("audio_source"), r.get("instrumental") and r["instrumental"].get("title"),
                                    r["instrumental"].get("source") if r.get("instrumental") else None)
                         for r in rows if r["stage"].startswith("2")})
    print("settings:", json.dumps(settings))
    return {"rows": rows, "settings": settings, "dir": str(out), "info": result.info}


if __name__ == "__main__":
    a, b = int(sys.argv[1]), int(sys.argv[2])
    run(a, b, *(sys.argv[3:5]))

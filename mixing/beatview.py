"""Beat view: a vocal-light version of a normal preview, no ML.

Used when no official instrumental exists. Steps:
  1. librosa HPSS, keep the PERCUSSIVE part (drums, hats, clap).
  2. Optionally mix back the original's low end (below
     config.BEATVIEW_LOW_END_HZ) so kick and 808/bass are present -- trap
     beats depend on them and vocals sit mostly above that range.
  3. Normalize to avoid clipping.

HONEST LIMITS (also shown in the UI):
  * It sounds THIN -- no melody/chords. It shows whether grooves lock, not
    how the full blend sounds.
  * Some vocal transients (consonants, ad-libs) leak through percussive.
  * Does NOT use centre-channel cancellation (that also deletes kick/bass).
  * It cannot move the 30-second window: if the clip is the wrong section
    of the song, the beat view of it is the wrong section too.
"""
from __future__ import annotations

import librosa
import numpy as np

import config
from mixing.styles import split_bands


def make_beat_view(
    y: np.ndarray,
    sr: int,
    add_low_end: bool | None = None,
    low_end_hz: float | None = None,
) -> np.ndarray:
    add_low_end = config.BEATVIEW_ADD_LOW_END if add_low_end is None else add_low_end
    low_end_hz = config.BEATVIEW_LOW_END_HZ if low_end_hz is None else low_end_hz

    _harmonic, percussive = librosa.effects.hpss(y, margin=config.BEATVIEW_HPSS_MARGIN)
    out = percussive
    if add_low_end:
        low, _high = split_bands(y, sr, cutoff_hz=low_end_hz)
        out = percussive + low * 0.9

    peak = float(np.max(np.abs(out))) if len(out) else 0.0
    if peak > 0:
        out = out / peak * 0.9
    return out.astype(np.float32)

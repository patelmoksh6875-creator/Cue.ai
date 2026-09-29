# Cue.ai

A personal, local-only tool that helps a DJ pick the next song to mix. Give
it a seed song and it returns a ranked list of `RESULT_COUNT` (default 20)
candidates that fit on BPM, key, genre, and vibe — matched deterministically
by signal processing and scoring code, not by an LLM (LLMs can't hear audio).
Groq is used only to expand free-text vibe queries and explain the top 3
results in prose.

Current scope is song matching only. Transition timestamps, vocal-swap
suggestions, stems, and mix previews are intentionally out of scope (see
`CLAUDE_HANDOFF.md` §9).

## Requirements

- Python 3.11 (librosa/numba don't yet support newer CPython releases —
  check `python3.11 --version` and use it explicitly for the venv below)
- [ffmpeg](https://ffmpeg.org) on your `PATH` (`brew install ffmpeg` on macOS)
  — needed to decode preview MP3s for librosa
- A free [Last.fm API key](https://www.last.fm/api/account/create)
  (optional — without it, candidate discovery falls back to Deezer-only
  sources and matching falls back to genre-only, both automatically)
- A free [Groq API key](https://console.groq.com/keys) (optional — without
  it, the pipeline runs fully deterministic with templated explanations)
- Deezer's public API needs no key at all

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env and add LASTFM_API_KEY / GROQ_API_KEY if you have them
```

The SQLite database (`cue.sqlite3`) is created automatically on first run —
no separate migration step.

## Running it

```bash
source .venv/bin/activate
streamlit run app.py
```

This opens the UI in your browser with two modes:
- **Find matches**: search for a seed song, click "Find matches", and get a
  sortable ranked list of up to 20 candidates with a full score breakdown.
- **Score a pair**: pick two songs directly and see how well they'd mix.

### Command-line pipeline (no UI)

```python
from db import repo
from sources import deezer
from matching import candidates

repo.init_db()
seed = deezer.get_track_detail(deezer.search_tracks("One More Time Daft Punk", limit=1)[0].id)
results = candidates.run_match_pipeline(seed)
for r in results:
    print(r.track.title, r.track.artist_name, r.breakdown.total, r.breakdown.label)
```

## Project layout

```
config.py               weights, thresholds, API keys, versions -- change tuning here, nowhere else
sources/deezer.py        ALL Deezer calls (search, detail, related, charts, preview URLs)
sources/lastfm.py        ALL Last.fm calls (tags, similar tracks)
analysis/audio.py        librosa: BPM verification, key/Camelot, energy
matching/scoring.py      pure scoring functions, no I/O -- fully unit-tested
matching/candidates.py   candidate discovery, fuzzy resolve, dedupe, full pipeline orchestration
db/schema.sql            schema
db/repo.py               the ONLY file that touches SQL
agent/groq_agent.py      Groq tool-calling: query expansion, top-3 explanations, deterministic fallback
app.py                   Streamlit UI
tests/                   pytest unit tests + verify_stageN.py manual verification scripts
```

Rules this codebase follows: nothing outside `db/repo.py` writes SQL;
nothing outside `sources/` calls an external API directly; scoring
functions in `matching/scoring.py` are pure (no I/O, no database).

## Re-analyzing after a code change

Audio analysis results are cached in the `audio_features` table, keyed by
Deezer track ID and stamped with `config.ANALYZER_VERSION`. If you change
how `analysis/audio.py` computes BPM/key/energy, bump `ANALYZER_VERSION` in
`config.py` — every track will be re-analyzed on its next lookup instead of
serving a stale cached result, and old rows stay around for comparison.

Likewise, if you change the scoring weights or thresholds in `config.py`,
bump `CONFIG_VERSION` so `match_runs` rows can be told apart by which
config produced them.

## Known limitations (by design, not oversights)

- **Deezer BPM is often missing or wrong by 2x** (half/double-time). Every
  candidate that survives the cheap pre-filter gets a librosa-verified BPM;
  disagreements are flagged explicitly.
- **librosa key detection is mediocre** on 30-second previews, so key is
  always a *soft* score, never a hard filter.
- **Deezer previews are 30s from the middle of the track**, not the full
  song, so BPM/key/energy estimates are approximate — `bpm_confidence` is
  stored so this can be surfaced later if needed.
- **Last.fm tags are sparse for obscure tracks.** When either side of a
  comparison has zero tags, `tags_score` returns `None` (not 0), and
  `total_score` renormalizes the remaining weights instead of unfairly
  zeroing out an otherwise-good match.
- **Fewer than 20 results can come back** for unusual BPMs or obscure
  seeds. The pipeline reports the real count rather than padding with
  poor matches.
- **Without a `LASTFM_API_KEY`**, candidate discovery silently degrades to
  Deezer-only sources (related artists + genre charts). This is the
  documented fallback, not a bug — you'll see a note about it in the CLI
  scripts and a smaller candidate pool as a result.
- **Without a `GROQ_API_KEY`**, `config.GROQ_ENABLED` is `False` and the
  app shows a "Groq disabled" caption with templated (not LLM-written)
  explanations for the top 3 results. Matching itself is unaffected either
  way — Groq never touches scores.
- **A `search_tracks(query, limit=1)` call can resolve to the wrong
  recording** (a cover, remix, or tribute) if Deezer's own search ranking
  puts one above the original — seen once in the 10-seed check below,
  where "Rolling in the Deep Adele" resolved to a drum & bass tribute
  cover instead of the original. The Streamlit UI avoids this by showing
  a `st.selectbox` of the actual search results so the user picks the
  right track; a raw CLI/script call with `limit=1` does not have that
  safety net.

## Development status

All 8 build stages from `CLAUDE_HANDOFF.md` are implemented and verified:
scaffold/DB, Deezer adapter, librosa analysis, scoring engine, Last.fm +
candidate discovery, Streamlit UI, Groq agent, and this hardening pass.
The Last.fm and Groq integrations were verified only via their documented
no-key fallback paths and mocked unit tests in this environment (no
personal API keys were available) — add real keys to `.env` and re-run
`tests/verify_stage5.py` / the app to see the full-strength behavior.

`tests/verify_stage8.py` ran the full live pipeline on 10 seeds spanning
house, pop, rock, DnB, and synth-pop:

| Metric | Result |
|---|---|
| Average result count | 20.0 / 20 |
| Average top-match score | 0.83 |
| Average runtime per seed (warm chart/related cache) | 31.3s |
| Seeds meeting a basic usability bar (≥15 results, top score ≥0.6) | 9 / 10 |

The one seed that didn't clear the bar ("Rolling in the Deep") is the
wrong-recording case described above, not a matching failure — the
`_analyze_candidate` cache reuse and the fix to stop double-fetching
preview URLs per candidate (see git history) cut per-seed runtime from
several minutes to well under a minute on a warm cache.

Run the test suite with:

```bash
pytest
```

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

One command, from the project root:

```bash
python cue.py
```

(A terminal can't literally run `run cue.py` — the command is `python cue.py`.)

This starts the Cue server as a **detached background process** (using the
same Python interpreter that ran `cue.py`, so there's no "wrong venv"
confusion), waits for it to come up, opens your browser to it, prints one
line, and **returns you to the terminal prompt** — the terminal is not
needed afterward. If port 8765 is already busy, it automatically picks the
next free one. Running `python cue.py` again while Cue is already running
just opens another browser tab to it instead of starting a second server.

**On macOS, the recommended way to open Cue day to day is `Cue.app`** — a
real app bundle, so double-clicking it never opens a Terminal window at
all (unlike a `.command` file, which is *defined* to open in Terminal no
matter what it runs). Generate it once:

```bash
python cue.py install-app
```

This creates `Cue.app` in the project folder and offers to copy it to
`~/Applications` so it shows up in Launchpad and Spotlight, and can be
dragged to the Dock. Double-click it (or Spotlight-search "Cue") to launch
— it starts the server and opens your browser with no terminal involved.
Double-clicking it again while Cue is already running just opens another
browser tab, same as `python cue.py`. The first time you open it, macOS
will likely say it's from an "unidentified developer" — right-click
`Cue.app` and choose **Open** once to allow it. All its output goes to
`logs/cue.log`; if it fails to start, it shows a native dialog explaining
why (there's no terminal to print to) with the reason and the log path.

`cue.command` still exists as a documented fallback if you'd rather not
generate an app bundle, but it does open (and auto-close) a Terminal
window — `Cue.app` is the one that never shows one at all.

**Stopping it:**

```bash
python cue.py stop      # stops the server
python cue.py status    # shows whether it's running, and where
python cue.py logs      # prints the server log (logs/cue.log)
```

There's also a **Quit Cue** button in the web UI's top bar.

If something's missing, `cue.py` tells you exactly what and exits cleanly
(no stack trace):
- **Python too old** — install Python 3.11 and recreate `.venv` (see Setup).
- **Dependencies missing** — activate the virtualenv and run
  `pip install -r requirements.txt`.
- **ffmpeg missing** — it prints an OS-specific install command
  (`brew install ffmpeg` on macOS) and exits; fix it and re-run.
- **No `.env` file** — it tells you to copy `.env.example` to `.env`, but
  still launches, since deterministic matching works without any keys.

To reset the cache (e.g. after changing scoring weights or wanting a clean
slate), just delete the database file:

```bash
rm cue.sqlite3
```

It's recreated automatically on the next launch.

`cue.py` is a thin launcher only — it contains no app logic. All UI code is
plain HTML/CSS/JS in `web/`, served by the FastAPI app in `server/`; if
you'd rather run the server directly for development (foreground, with logs
in your terminal instead of `logs/cue.log`), `uvicorn server.main:app
--host 127.0.0.1 --port 8765 --reload` works too.

The web UI has two modes:
- **Find matches**: search for a seed song, click "Find matches", and get a
  filterable, sortable ranked list of up to 20 candidates (from a larger
  scored pool) with BPM, key, genre, and percent match.
- **Preview mix**: on any result, generate a short audio sample of how the
  seed and that track might blend (see Mix snippets below).

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
cue.py                   launcher: start/stop/status/logs/install-app, detached server, opens browser
Cue.app                  generated by `cue.py install-app` -- gitignored, bakes in an absolute path
cue.command              fallback double-click launcher (opens/auto-closes Terminal; Cue.app doesn't)
config.py                weights, thresholds, API keys, versions -- change tuning here, nowhere else
sources/deezer.py        ALL Deezer calls (search, detail, related, charts, preview URLs)
sources/lastfm.py        ALL Last.fm calls (tags, similar tracks)
analysis/audio.py        librosa: BPM verification, key/Camelot, energy
matching/scoring.py      pure scoring functions, no I/O -- fully unit-tested
matching/candidates.py   candidate discovery, fuzzy resolve, dedupe, full pipeline orchestration
db/schema.sql            schema
db/repo.py               the ONLY file that touches SQL
agent/groq_agent.py      Groq tool-calling: query expansion, top-3 explanations, deterministic fallback
mixing/                  mix snippet maker: align.py, render.py, styles.py
server/main.py           FastAPI app: route registration, static file mount, 127.0.0.1 only
server/routes/           search.py, match.py, preview.py, mix.py -- thin, call existing modules
server/jobs.py           in-memory job tracking for long-running match/snippet runs
web/                     plain HTML/CSS/JS frontend -- no framework, no build step
tests/                   pytest unit tests + verify_stageN.py manual verification scripts
```

Rules this codebase follows: nothing outside `db/repo.py` writes SQL;
nothing outside `sources/` or `agent/` calls an external API directly;
scoring functions in `matching/scoring.py` are pure (no I/O, no database);
API keys never reach the browser -- every external call happens server-side.

## API contract

| Method and path | Purpose |
|---|---|
| `GET /api/health` | Used by the launcher to know the server is up |
| `GET /api/search?q=` | Deezer search for picking a seed song |
| `POST /api/match` `{seed_id}` | Starts a match run, returns `{job_id}` |
| `GET /api/match/{job_id}` | Poll: `status` (queued/running/done/error), `progress` text, `result` (seed + up to `RESULT_POOL` scored results) when done |
| `GET /api/preview/{track_id}` | Streams a fresh Deezer preview server-side (never hands the browser a raw signed URL) |
| `POST /api/mix-snippet` `{a_id, b_id, style, length_seconds}` | Cache hit: `{job_id: null, snippet_url}` immediately. Otherwise `{job_id, snippet_url: null}` -- poll it |
| `GET /api/mix-snippet/{job_id}` | Poll: same shape as `/api/match/{job_id}`; `result` has `snippet_url`, `warnings`, and the honest limitations `note` |
| `GET /api/snippet/{id}.mp3` | Serves a rendered snippet |
| `POST /api/shutdown` | Cleanly stops the server (self-SIGTERM after responding) -- used by the Quit Cue button and `cue.py stop` |

Long-running work (a cold match run, or a first-time snippet render) always
uses the job + polling pattern above, never one long request.

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
  cover instead of the original. The web UI avoids this by showing a
  dropdown of the actual search results so the user picks the right
  track; a raw CLI/script call with `limit=1` does not have that safety
  net.

## Mix snippets

"Preview mix" generates a 10-15s sample of how the seed and a result
might blend: tempo-matches (respecting half/double-time), picks a
beat-aligned offset by maximizing low-frequency onset overlap, and mixes
a transition in one of three styles (blend = EQ bass-swap crossfade, cut
= hard cut with an echo tail, echo-out = beat-synced decaying echo).
Rendered snippets are cached by `(a_id, b_id, style, length,
analyzer_version)` so repeat clicks are instant, and the cache is
cleared on server shutdown (personal use only -- no persistent library
of derived preview audio is kept between runs).

**This is a sample, not a finished mix, and the UI says so every time.**
Known limitations, by design:
- The only audio available is Deezer's 30s preview clips -- an arbitrary
  slice of the song, not its real intro/outro. The snippet shows how the
  two songs *sound* together (tempo, key, feel), not where the real
  transition should happen in the full tracks.
- Both previews can happen to contain vocals at the same moment, which
  sounds messy -- detecting that needs stem separation or lyric timing,
  out of scope for v1.
- A large tempo stretch, a key clash, or a low-confidence BPM estimate
  all degrade the result even for a genuinely good pair; the UI surfaces
  each of these as a warning rather than silently producing a bad-sounding
  snippet and leaving the user to blame the song choice.
- Some tracks have no Deezer preview at all in some regions; the API
  returns a clear error rather than a broken snippet.
- Rendering takes a few seconds of CPU time -- it only happens on click,
  per result, never upfront for all 20.

## Development status

All 8 build stages from `CLAUDE_HANDOFF.md` are implemented and verified:
scaffold/DB, Deezer adapter, librosa analysis, scoring engine, Last.fm +
candidate discovery, a web UI, Groq agent, and a hardening pass. The
original Streamlit UI (`CLAUDE_HANDOFF.md` Stage 6) was later replaced
entirely by a FastAPI server + plain HTML/CSS/JS frontend per
`CLAUDE_HANDOFF_V2_WEB_UI.md` -- see that file and the V2 commits for
what changed and why.
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
several minutes to well under a minute on a warm cache. All of this ran
against the original Streamlit UI; the matching engine itself (the part
that produced these numbers) is unchanged by the V2 rewrite.

V2 (`CLAUDE_HANDOFF_V2_WEB_UI.md`) replaced Streamlit with a FastAPI
server + plain HTML/CSS/JS frontend, rewrote the launcher to run as a
detached background process (`cue.py start/stop/status/logs`), added a
client-side artist/genre filter bar over a larger scored result pool,
and added the mix snippet maker (all three styles). Verified live on
macOS with Python 3.11: the full browser flow end to end (search, match
with progress, filtering, on-demand preview, all three mix-snippet
styles playing back correctly), the launcher's start/stop/status/logs
and stale-PID-file self-healing, log rotation, and the snippet-cache
cleanup on shutdown. Not tested on Linux/Windows — the ffmpeg install
hints and `cue.command`-equivalent for those platforms are unverified.

Run the test suite with:

```bash
pytest
```

(117 tests as of this writing: scoring, repo round-trips, adapters
against mocked responses, candidate discovery/fuzzy-matching, the Groq
agent's deterministic fallback path, the launcher's pure/file-based
logic, and the mix snippet maker's DSP functions.)

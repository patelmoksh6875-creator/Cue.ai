# Cue V2 — Web UI (HTML/CSS/JS), New Launcher, App Changes, Mix Snippet Maker

## Read this first: what this file changes
This file **supersedes the UI and launcher parts** of earlier handoffs:
- `CLAUDE_HANDOFF.md`: Stage 6 (Streamlit UI) and every mention of Streamlit are replaced by this file. The matching engine, database design, scoring, source adapters and Groq agent stay exactly as specified there.
- `CLAUDE_CUE_LAUNCHER.md` and `CLAUDE_LOCALHOST_SETUP.md`: the launcher behavior and run instructions are replaced by Section 5 below. Keep their useful parts (ffmpeg check, `.env`, clean setup).
- `CLAUDE_FIX_VERCEL_DEPLOY.md` and `CLAUDE_DEPLOY_STREAMLIT_CLOUD.md`: obsolete. There is no hosting; the app runs on localhost only.

Project: a personal, non-commercial DJ song-matching tool called **Cue** (the user calls the launcher `cue.py`). Runs locally on the user's computer (macOS, uses Finder).

## 1. Goals of V2
1. **Remove Streamlit completely.** UI is plain **HTML, CSS and JavaScript files** (no framework, no npm, no build step).
2. **`cue` opens the web app directly.** The user should not be left sitting in a terminal.
3. **App function changes:** filter bar (artists, genres), actual BPM numbers, genre names, percent match.
4. **New feature:** an **auto mix snippet maker** that generates a 10–15 second audio sample of how two songs might blend.

The matching logic the user likes ("the function of the app is awesome") must not regress. Do not change scoring behavior unless a section below says so.

## 2. Architecture change
Streamlit used to be both the server and the UI. Now there are two parts:

```
Browser (web/index.html + styles.css + app.js)
        |  fetch() calls to /api/...
        v
Local Python server (FastAPI + uvicorn), bound to 127.0.0.1 only
        |
        v
Existing modules: sources/, analysis/, matching/, db/, agent/
```

- **Two new Python dependencies are approved: `fastapi` and `uvicorn`.** They replace Streamlit as the local server. The browser cannot run Python, so some server is required; FastAPI is the smallest sensible option. Add nothing else without asking the user.
- The server also serves the static files in `web/`. No Node, no npm.
- **Bind to `127.0.0.1` only.** Never `0.0.0.0` unless the user asks.
- **API keys never reach the browser.** All Deezer, Last.fm and Groq calls stay server-side in `sources/` and `agent/`.
- Keep module boundaries: no SQL outside `db/repo.py`, no external API calls outside `sources/`, scoring stays pure. Route handlers are thin: they call existing modules and return JSON.

### Updated code layout
```
cue.py                 launcher (Section 5)
server/main.py         FastAPI app, route registration, static file mount
server/routes/         search.py, match.py, preview.py, mix.py, system.py
server/jobs.py         in-memory job tracking for long runs
web/index.html
web/styles.css
web/app.js             (split into small files if it grows: api.js, ui.js, filters.js)
mixing/                snippet maker (Section 6): align.py, render.py, styles.py
config.py, sources/, analysis/, matching/, db/, agent/, tests/   (unchanged from before)
```

### API contract (initial)
| Method and path | Purpose |
|---|---|
| `GET /api/health` | Returns ok; used by the launcher to know the server is up |
| `GET /api/search?q=` | Deezer search for picking a seed song |
| `POST /api/match` body `{seed_id}` | Starts a match run, returns `{job_id}` |
| `GET /api/match/{job_id}` | Poll: status (`queued/running/done/error`), progress text, and results when done |
| `GET /api/preview/{track_id}` | Server fetches a **fresh** Deezer preview URL and streams the audio (preview URLs expire and may block cross-origin use, so never hand raw URLs to the browser) |
| `POST /api/mix-snippet` body `{a_id, b_id, style, length_seconds}` | Builds a mix snippet, returns `{snippet_url}` or a job id |
| `GET /api/snippet/{id}.mp3` | Serves the rendered snippet |
| `POST /api/shutdown` | Cleanly stops the server (used by a "Quit Cue" button and `cue stop`) |

Long runs (cold match can take a minute or more) **use the job + polling pattern**, not one long request. The UI shows live progress text ("Fetching candidates…", "Analyzing 14/42…").

## 3. App function changes

### 3.1 Filter bar (artists and genres)
- A filter bar above the results: multi-select for **artists** and **genres**, plus a clear-filters button. Populated from the actual results (only offer values that exist).
- **Important design decision:** the backend returns a larger **scored pool** (`RESULT_POOL`, default 60, configurable) sorted by match score. The UI shows the top `RESULT_COUNT` (default 20) **after filtering**. This way filtering by an artist or genre refills the list from the pool instead of leaving 3 results. Filtering happens client-side on the pool, so it is instant.
- If the filtered pool has fewer than `RESULT_COUNT`, show what exists and say so ("Only 7 matches for Genre X in this pool"). Offer a "Search wider" button that re-runs candidate discovery biased toward the chosen genre/artist (implement after the basic filter works).
- Filters are combined with AND across fields (artist AND genre), OR within a field.
- Also keep sorting: by match %, BPM, key.

### 3.2 Actual BPM number
- Show each song's **BPM as a number** (verified librosa BPM, rounded to a whole number), and the seed's BPM prominently at the top.
- When half/double-time logic was used to match, show it explicitly (e.g. "70 BPM (half-time of 140)").
- Flag low-confidence BPMs with a small marker and tooltip; never present an uncertain value as certain. If only Deezer's BPM exists (analysis not finished), show it marked as "unverified".

### 3.3 Genre name
- Show the **genre name** for every result (Deezer genre, stored at album level). If Deezer has none, fall back to the top Last.fm tag, clearly labeled as a tag. Never leave the field blank; use "Unknown".
- Genre filter uses these same names. Normalize names (case, spacing) so filters don't split "Hip Hop" and "Hip-Hop".
- Make sure `db/repo.py` returns artist name and genre name with each result (joins), with indexes for the lookups.

### 3.4 Percent match
- Replace decimal scores with a **percent match**: `round(100 * total_score)`, clamped to 0–100, shown as "87% match". Weights in `config.py` must sum to 1 so `total_score` is 0–1; add a test for this.
- Show the component breakdown on hover or expand (BPM, key, vibe, genre, energy), also as percentages.
- Note for documentation: this is a **relative match score from the weighted factors**, not a probability that the mix will sound good. Do not label it as "accuracy" or "chance".
- Use simple visual bands (for example strong / good / fair) so the number is easy to scan.

### 3.5 Unchanged behavior
Top results, safe/adventurous labels, artist diversity cap (max 2 per artist), dedupe by ISRC/title, "fewer than N" honesty, and the deterministic fallback when Groq is down all stay.

## 4. Frontend spec (vanilla HTML/CSS/JS)
- **No frameworks, no npm, no build tools, no CDN dependencies** (must work offline apart from the API calls the server makes). System font stack.
- Layout: top bar (name, status, Quit button) · seed search box with results dropdown · seed card (title, artist, BPM, key, genre, preview player) · "Find matches" button with live progress · filter bar · results table/cards (rank, title, artist, genre, BPM, key, % match, safe/adventurous tag, play preview, "Preview mix" button).
- Audio: `<audio>` elements pointing at `/api/preview/{id}`; only one plays at a time.
- States to handle: empty, loading with progress, partial results, errors (API down, rate-limited, missing keys with a clear message), fewer-than-N results.
- Responsive enough to be usable on a laptop window of any size. Clean, minimal, dark theme suitable for DJ use. Keyboard-friendly (Enter to search, Space to play/pause focused preview).
- Escape all text inserted into the DOM (song titles come from external APIs; avoid `innerHTML` with untrusted strings).
- Keep JS modular and commented so the user can edit it.

## 5. `cue` launcher (goes straight to the web app)
**Requirement:** the user runs one command and lands in the browser at the app. The terminal must not be needed afterward.

Be honest about the constraint: the Python server has to keep running somewhere while the app is used. The solution is to **run it as a background process**, not in the foreground terminal.

`cue.py` behavior:
1. Pre-checks (Python version, `fastapi`/`uvicorn`/`librosa` import, `ffmpeg` on PATH, `.env` present). Clear one-line errors, no stack traces.
2. If a Cue server is already running (PID file plus `/api/health` responds), **just open the browser** to it.
3. Otherwise start uvicorn as a **detached background process** using `sys.executable -m uvicorn server.main:app --host 127.0.0.1 --port <CUE_PORT>` (default 8765; pick the next free port if taken and record it). Redirect its output to a log file (`logs/cue.log`), write a PID file.
4. Poll `/api/health` until ready (timeout with a helpful message pointing at the log).
5. Open the default browser to `http://127.0.0.1:<port>` with `webbrowser.open`.
6. Print one line ("Cue is running at …; `python cue.py stop` to quit") and **exit**, returning the terminal to the user.

Subcommands: `python cue.py stop` (graceful via `/api/shutdown`, fall back to the PID), `python cue.py status`, `python cue.py logs`. The web UI also has a **Quit Cue** button calling `/api/shutdown`.

**Mac double-click launcher (no visible terminal):**
- Provide `cue.command` that runs `python cue.py` and then closes its own Terminal window (via `osascript`). Mark it executable.
- Ask the user whether they want a proper **Cue.app** (Automator or AppleScript wrapper that runs the launcher silently, with a Dock icon). Build it only if they say yes.
- Explain the macOS "unidentified developer" prompt: right-click → Open the first time.
- Optional alias so the user can type just `cue` (give exact lines; don't edit the user's shell profile without asking).

## 6. Auto Mix Snippet Maker
### What it is
For any result, a **"Preview mix"** button generates a **10–15 second audio sample** of how the seed song and that song might blend, so the user can judge compatibility by ear before doing the real mix. It is a sample, not a finished mix.

### Hard constraint (design around it, tell the user)
The only audio available is Deezer's **30-second preview clips**, taken from somewhere in the song, not the actual outro/intro. So the snippet shows **how the two songs sound together** (tempo, key, feel, vocal clash), **not the exact place in the full tracks where the real transition should happen**. Exact transition points need full-track analysis of files the user owns (a later phase). The UI must say this plainly.

### Pipeline
1. Fetch both previews (fresh URLs server-side), decode via ffmpeg, cache in a temp directory with cleanup. Personal use only: do not build a persistent library of preview audio; delete temp files on a schedule and on shutdown.
2. Reuse the stored analysis (BPM, beat times, key) from `audio_features`; re-analyze only if missing or low confidence.
3. **Tempo match:** time-stretch song B toward song A's BPM (respect half/double-time). Flag when the stretch exceeds about 6–8%, since quality and feel degrade; warn in the UI.
4. **Beat alignment:** librosa gives beats, not bars/downbeats, so alignment can be off by a beat within a bar. Approach: generate candidate offsets (within one bar, about 4 beats) and pick the one that maximizes low-frequency onset (kick) overlap between A and B. Evaluate; report honestly how often it lands right.
5. **Key handling:** if keys are incompatible on the Camelot wheel, either warn or (optional, later) pitch-shift B by up to about ±2 semitones. Start with warn-only.
6. **Render** a 10–15 s snippet (`length_seconds`, default 12; allowed 10–15), structure: a few seconds of A alone → blend/transition section (about 4–8 bars' worth, or less at slow tempos) → a few seconds of B alone.
7. Export MP3 (via ffmpeg), serve at `/api/snippet/{id}.mp3`, cache by `(a_id, b_id, style, length, analyzer_version)` so repeat clicks are instant.

### Snippet styles (implement in this order; each is a function in `mixing/styles.py`)
1. **Blend** (default): beat-matched crossfade with an **EQ bass swap** (A's low end is cut as B's comes in, using simple filters), the standard DJ transition.
2. **Cut**: hard cut on a beat boundary, optionally with a short echo/reverb tail on A.
3. **Echo-out**: A fades into a beat-synced echo while B drops in.
4. **Vocals over beat** (later, optional): needs stem separation (Demucs), which is heavy and not in the approved dependency list. Ask the user before adding it. Until then, do not fake it.

Implementation notes: start with numpy plus librosa plus soundfile (already in the stack) and ffmpeg for encoding. `librosa.effects.time_stretch` quality is mediocre; test it on real songs and only propose a better stretcher (for example the rubberband library) if the user finds it too poor. Ask before adding any dependency.

### Known problems (document them in the README and UI)
- Both previews may contain **vocals at the same moment**, which sounds messy. A clash detector needs stems or lyrics timing; out of scope for v1, so just tell the user this can happen.
- Wrong BPM or beat detection → off-grid snippet that sounds bad even for a good pair. Show BPM confidence next to the snippet; don't blame the songs.
- Preview clips may come from different song sections (verse vs drop), so the feel is approximate.
- Some tracks have no preview in some regions; handle gracefully.
- Rendering takes CPU time (several seconds). Use the job pattern and show progress; render only on click, never for all 20 results upfront.
- Audio is for personal use only; do not redistribute or persist it.

## 7. Stages
Complete each stage, verify, and commit before moving on. Do not claim a stage works unless it has been run.

1. **Audit and remove Streamlit.** Find every Streamlit import and use (`app.py`, `st.session_state`, caching, config, requirements, `packages.txt`, `.streamlit/`). List what logic lives in the UI that must move to a module. Remove Streamlit from dependencies. *Done when:* no Streamlit remains and the matching logic runs from a plain Python script.
2. **Server skeleton.** `server/main.py` with `app = FastAPI()`, `/api/health`, static mount for `web/`, 127.0.0.1 binding, and the job system. *Done when:* `uvicorn` serves a blank page and health check.
3. **Core API.** Search, match job and polling, preview streaming. Include the larger `RESULT_POOL`. *Done when:* curl/browser can run a full match and get JSON with BPM, genre name, artist, key, and `match_pct` per track.
4. **Frontend v1.** Seed search, seed card, Find matches with progress, results list with actual BPM, genre names, percent match, working preview players. *Done when:* the full flow works in the browser.
5. **Filter bar.** Artist and genre multi-selects, pool-based refilling, sort options, "only N matches" messaging. *Done when:* filters are instant and never crash on empty results.
6. **Launcher.** `cue.py` background start, health wait, open browser, `stop/status/logs`, Quit button, `cue.command`. *Done when:* `python cue.py` opens the app and returns the terminal; `stop` shuts it down cleanly; a second run doesn't start a duplicate server.
7. **Snippet maker v1.** Tempo match, beat alignment, **Blend** style, `/api/mix-snippet`, "Preview mix" button with progress and a player, honest limitations note. Then **Cut** and **Echo-out**. *Done when:* the user can click Preview mix on real pairs and judge the output; report how often alignment worked on a test set of pairs.
8. **Harden and document.** Error states, temp file cleanup, log rotation, tests for scoring (weights sum to 1, percent conversion), filter logic, snippet cache keys, and API contract. README: setup, `python cue.py`, stopping, limits, what resets. *Done when:* a fresh clone can run from the README.

## 8. Rules
- Ask before adding any dependency beyond `fastapi` and `uvicorn`.
- No secrets in git or in frontend code. `.env` stays git-ignored.
- Server binds to localhost only.
- Never use `innerHTML` with external data; escape everything.
- Be honest in the UI about confidence, unverified values, and snippet limitations.
- Keep files small and modules single-purpose so the user can change code easily.
- Report what was actually tested (and on which OS); do not claim success otherwise.

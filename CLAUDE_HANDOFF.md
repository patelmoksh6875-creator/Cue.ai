# Personal AI DJ Assistant — Claude Code Handoff

## 1. Project goal
A personal tool (single user, runs locally) that helps a DJ pick songs to mix. The user selects a **seed song** inside the tool, runs it, and the tool returns a ranked list of **20 songs that fit** (matching BPM, key, genre, vibe). The count is a setting (`RESULT_COUNT = 20` in `config.py`), not hardcoded. Optional second mode: user picks both songs and the tool scores the pair.

**Current scope: song matching only.** Transition timestamps, vocal-swap suggestions, stems and mix previews are out of scope for now (see Section 9).

## 2. Hard constraints
- **Completely free.** No paid APIs, no paid tiers.
- **No bulk database download.** Query APIs live; cache only what is touched in SQLite.
- **Spotify is NOT usable.** Since Nov 2024, new apps get 403 on audio-features, audio-analysis and recommendations, and `preview_url` is null. Do not build on Spotify.
- **Groq LLMs cannot hear audio.** Audio analysis is done by signal processing (librosa). The LLM only expands queries and explains results. Deterministic code makes the matching decisions.
- The user is a developer. Keep code clean, modular, and easy to change.

## 3. Tech stack (and why)
| Tool | Role | If removed |
|---|---|---|
| Python 3.11+ | Everything | Audio libs are Python-first |
| Deezer public API (no auth) | Search, track detail incl. BPM, album genre, 30s preview, related artists, charts | No song source |
| Last.fm API (free key) | Crowd tags for vibe; `track.getSimilar` for candidate discovery | Vibe falls back to coarse genre only |
| librosa | Verify BPM on preview; estimate key and energy | Deezer BPM is often missing or half/double, so matches silently wrong |
| ffmpeg | Decode preview MP3s for librosa (also needed later for mixing) | Random decode failures |
| SQLite (`sqlite3` stdlib) | Cache + store all data | Repeated API hits, rate limits, no history |
| Groq API (free tier, tool calling) | Query expansion, explanation of picks. **Optional; build last.** Models: primary `openai/gpt-oss-120b` (Apache 2.0), fallback `llama-3.3-70b-versatile`, cheap query-expansion `llama-3.1-8b-instant`. All names live in `config.py`, never hardcoded | Core matching still works |
| Streamlit | UI: search, select seed, run, show a ranked list of 20 results with `st.audio` | Falls back to CLI |
| python-dotenv | API keys from `.env` | Key leaks into git |
| httpx | Single HTTP client for all APIs | Use `requests` instead, but only one |
| pytest | Test scoring functions | Weight changes break things unseen |
| Git | Version control | Can't undo |

**Deliberately excluded:** Spotify, MusicBrainz, Essentia (hard to install), Demucs, pydub, sentence-transformers/embeddings, FastAPI, React, SQLAlchemy, pydantic, Docker. Each duplicates something above or is not needed yet. Do not add them without a stated reason.

## 4. Code layout
```
config.py             weights, thresholds, API keys, versions
sources/deezer.py     ALL Deezer calls (adapter)
sources/lastfm.py     ALL Last.fm calls (adapter)
analysis/audio.py     librosa: bpm, key, camelot, energy
matching/scoring.py   pure functions, no I/O, unit-tested
matching/candidates.py candidate discovery
db/schema.sql         schema
db/repo.py            the ONLY file that touches SQL
agent/groq_agent.py   LLM tools, prompts, fallback
app.py                Streamlit UI
tests/
.env.example
```
**Rules:** nothing outside `db/repo.py` writes SQL. Nothing outside `sources/` knows an external API exists (so swapping Deezer is a one-file change). Scoring functions are pure and take plain data.

## 5. Database design
Separate **raw API data** from **derived analysis** so analysis can be re-run without refetching. Primary key everywhere is the **Deezer track ID**.

- `tracks`: id, isrc, title, artist_id, album_id, duration, deezer_bpm, fetched_at. **Do not store preview URLs** (they are signed and expire). Re-fetch when needed.
- `artists`: id, name
- `albums`: id, title, genre (Deezer stores genre at album level)
- `tags`: track_id, tag, weight, source
- `audio_features`: track_id, bpm_verified, bpm_confidence, key, camelot, energy, analyzer_version, analyzed_at
- `match_runs`: run_id, seed_id, candidate_id, one column per score component, total, config_version, created_at

Use foreign keys, indexes on lookup columns, and a `schema_version` table with simple migrations. `analyzer_version` and `config_version` make re-analysis and weight comparisons possible.

## 6. Matching logic
1. **Seed:** user searches and selects a song. Fetch its BPM, genre, tags, preview.
2. **Candidates:** Last.fm similar tracks, related-artist top tracks, genre chart tracks. Resolve all to Deezer IDs.
3. **Hard filter (code):** BPM within about ±6%, also allowing half/double time. Key compatible on the Camelot wheel (adjacent numbers, or same number A/B). Treat key as a **soft score first**, since librosa key detection is mediocre.
4. **Score:** BPM closeness, key compatibility, tag overlap (Jaccard or TF-IDF), genre match, energy closeness. Weights live in `config.py`.
5. **Output:** the top `RESULT_COUNT` (20) tracks, ranked by total score. Label each as "safe" (tightest BPM and key) or "adventurous" (same vibe, different genre). Apply a diversity rule: max 2 tracks per artist and no duplicate versions, so the list is not 20 songs by one artist. Groq explains only the top 3 in prose (token limits); the rest show the score breakdown only. Log every result to `match_runs`.
6. **Pool size:** the candidate pool must be much bigger than 20 (target 100–200 before filtering) or the hard filters will leave fewer than 20. If fewer than 20 pass, return what passed and say so; never pad with poor matches.

"Tempo" and "BPM" are the same signal here. Energy is the separate "feel" signal.

## 7. Known problems to design around
- Preview URLs expire (signed). Store IDs, not URLs.
- BPM half/double confusion. Handle explicitly in scoring.
- Previews are 30s from the middle of the song. librosa estimates are approximate; store confidence and show it.
- librosa key detection is mediocre. Soft score.
- Last.fm tags are noisy and sparse. Define a fallback (genre only) so obscure tracks do not silently score zero.
- Deezer genre is album-level and coarse.
- Duplicate versions (remix, live, radio edit). Dedupe by ISRC and normalized title.
- Resolving Last.fm results to Deezer needs fuzzy matching (punctuation, featured artists).
- Deezer rate limit is roughly 50 requests per 5 seconds. Throttle and cache from day one.
- Groq free tier: rate limits and malformed tool-call JSON. Validate outputs, keep deterministic fallback.
- Streamlit reruns the whole script on every interaction. Use `st.session_state` and caching.
- librosa: slow first import (numba), install issues on Windows and Apple Silicon.
- Any API can change or restrict access (Spotify did). Keep adapters thin.
- **20 results means more work per run.** Roughly 100–200 candidates need Deezer detail calls and about 30–60 librosa analyses on a cold cache. Filter by BPM first, analyze lazily, cache everything, and consider running analysis in a small thread pool. Respect the Deezer rate limit.
- **Fewer than 20 may pass the filters** for unusual BPMs or obscure seeds. Handle that honestly (return fewer, say why).
- **Result quality drops down the list.** Rank 15–20 will be weaker than 1–5. Show the score so the user can judge, and tune weights using the lower ranks.
- **Groq token caps:** explain only the top 3, in one call.
- **Verify Deezer and Last.fm endpoint details against their current docs before coding.** Endpoint names in this document are from memory and may have changed.

## 8. Development stages
Complete each stage and confirm its "done when" before moving on. Commit at the end of each stage.

### Stage 1 — Scaffold, config, database
- Create the folder layout, virtualenv, `requirements.txt`, `.env.example`, `.gitignore` (include `.env` and the SQLite file).
- Write `config.py` (weights, thresholds, versions, env loading).
- Write `db/schema.sql` and `db/repo.py` (init, upsert and get functions for each table, schema_version).
- **Done when:** DB initializes from scratch, repo functions round-trip test data, pytest runs green on repo tests.

### Stage 2 — Deezer adapter
- `sources/deezer.py`: search tracks, get track detail (BPM, ISRC, duration), get album (genre), get artist related, chart by genre, get fresh preview URL for a track ID.
- Add throttling (about 50 req/5s), retries with backoff, and normalization into plain dicts or dataclasses. Persist through `repo.py`.
- **Done when:** a script searches a song, stores track, artist, album and genre, and prints BPM and a working preview URL. Repeated runs hit the cache, not the API.

### Stage 3 — Audio analysis
- `analysis/audio.py`: download preview to a temp file, decode via ffmpeg, run librosa for BPM (with confidence), key and mode, Camelot mapping, and energy.
- Store in `audio_features` with `analyzer_version`. Delete temp files.
- Compare against Deezer BPM and flag disagreements including half/double.
- **Done when:** on about 20 songs the user knows, verified BPM is correct for most, and the disagreement rate with Deezer is printed. Report accuracy honestly.

### Stage 4 — Scoring engine
- `matching/scoring.py`: pure functions for BPM score (with half/double), Camelot key score, tag overlap, genre match, energy closeness, weighted total driven by `config.py`.
- Full pytest coverage with edge cases (missing BPM, no tags, no key).
- **Done when:** tests pass and a script scores two hand-picked tracks with a readable component breakdown.

### Stage 5 — Last.fm adapter and candidate discovery
- `sources/lastfm.py`: track tags and `track.getSimilar` (verify endpoint names first). Store tags.
- `matching/candidates.py`: gather candidates from Last.fm similar, Deezer related-artist tracks, genre charts. Resolve to Deezer IDs with fuzzy matching, dedupe by ISRC and normalized title, apply the hard BPM filter before analysis to limit librosa work.
- **Done when:** given a seed, the tool returns a deduped candidate pool of about 100–200 tracks, runs the BPM hard filter before any audio analysis, then runs analyze, score and rank from a CLI, outputting the top 20 with a score breakdown. Analysis is lazy and cached, so a repeat run on the same seed is fast. Log to `match_runs`.

### Stage 6 — Streamlit UI
- `app.py`: search box, result selection for the seed, "Find matches" button, a ranked table of 20 results with BPM, key, genre, tags, score breakdown, safe/adventurous label, sortable by score, BPM or key. Fetch preview URLs on demand (on play), not for all 20 upfront. Show progress while candidates are analyzed.
- Second mode: pick both songs and show the pair score.
- Use `st.session_state` and caching. Show loading and error states.
- **Done when:** the full flow works end to end in the browser without redundant API calls on reruns.

### Stage 7 — Groq agent
- `agent/groq_agent.py`: tool-calling agent that turns a free-text vibe request ("summer beach vibe") into search queries and tags feeding the candidate stage, and writes a short explanation of why the top 3 fit (one batched call with compact JSON, not one call per song).
- Validate all model output. Rate limit handling. If Groq fails, the pipeline falls back to deterministic behavior with templated explanations.
- The LLM never overrides scores; it only supplies queries and prose.
- Models are set in `config.py` as an ordered list (primary, fallback, cheap). On startup, call Groq's list-models endpoint and drop any model no longer offered. On a 429 or a deprecated-model error, move to the next model in the list, then to the deterministic fallback. Free-tier limits and the model roster change (Groq deprecated models before), so verify against `console.groq.com/settings/limits` and current docs when starting this stage.
- Keep prompts small. Free tier has per-minute and per-day token caps (the 120B model is around 8K tokens/minute), so send compact JSON (BPM, key, tags, scores), not raw API responses.
- Use the 8B model for query expansion and the larger model only for the final explanation and tool-calling steps.
- **Done when:** results are equally correct with Groq disabled, and enabling it adds vibe-based querying and explanations.

### Stage 8 — Hardening and tuning
- Logging and error handling across adapters; clear messages when an API is down.
- Expand tests (adapters with mocked responses, dedupe, fuzzy resolve).
- Tune weights in `config.py` using `match_runs` on real songs; record what changed via `config_version`.
- Add a README: setup, `.env` keys, ffmpeg install, how to run, how to re-analyze after an `analyzer_version` bump.
- **Done when:** a fresh clone can be set up from the README, and the top 20 for 10 test seeds are judged usable by the user (roughly, most of the 20 are mixable), and a full run finishes in an acceptable time on a warm cache.

## 9. Future scope (do NOT build yet)
- Exact transition points, which need full-track audio, so analysis of the user's own files.
- Vocal-over-beat suggestions via Demucs stems.
- Rough two-song preview overlay: time-stretch song B to A's BPM, align downbeats, crossfade, export a WAV.
- Essentia for better key detection if librosa proves too inaccurate.

## 10. Working rules for Claude Code
- Read this file at the start of each session. Work one stage at a time.
- Ask before adding any dependency not listed in Section 3.
- Keep modules single-purpose; no SQL outside `db/repo.py`; no API calls outside `sources/`.
- Be honest about accuracy, limits and failures. Do not claim something works unless it has been run.
- Prefer simple, readable code over clever code.

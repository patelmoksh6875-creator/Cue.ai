"""Streamlit UI for Cue.ai. Two modes: find matches for a seed song, or
score a hand-picked pair. Search/detail calls are cached with
st.cache_data; preview URLs are only fetched on demand (when the user
clicks play), never upfront for all results.
"""
from __future__ import annotations

import streamlit as st

import config
from agent import groq_agent
from db import repo
from matching import candidates
from sources import deezer

st.set_page_config(page_title="Cue", page_icon="🎧", layout="wide")
repo.init_db()


@st.cache_data(show_spinner=False)
def cached_search(query: str, limit: int = 10):
    return deezer.search_tracks(query, limit=limit)


@st.cache_data(show_spinner=False)
def cached_detail(track_id: int):
    return deezer.get_track_detail(track_id)


def _preview_player(track_id: int) -> None:
    """Fetch a fresh preview URL only when the user asks for it -- Deezer
    preview URLs are signed/expiring, so we never fetch or store them
    upfront for every row in a results table."""
    key = f"preview_{track_id}"
    if st.button("Play preview", key=f"btn_{key}"):
        with st.spinner("Fetching preview..."):
            try:
                url = deezer.get_fresh_preview_url(track_id)
            except Exception as exc:
                st.error(f"Could not fetch preview: {exc}")
                return
        if url:
            st.audio(url, format="audio/mp3")
        else:
            st.warning("No preview available for this track.")


def _search_and_select(label: str, state_key: str):
    query = st.text_input(label, key=f"query_{state_key}")
    if not query:
        return None
    try:
        results = cached_search(query)
    except Exception as exc:
        st.error(f"Search failed: {exc}")
        return None
    if not results:
        st.warning("No results found.")
        return None
    options = {f"{t.title} — {t.artist_name}": t for t in results}
    choice = st.selectbox("Select a track", list(options.keys()), key=f"select_{state_key}")
    return options[choice] if choice else None


def render_find_matches() -> None:
    st.subheader("Find matches for a seed song")
    seed_stub = _search_and_select("Search for your seed song", "seed")

    if seed_stub is None:
        return

    if st.button("Find matches", type="primary"):
        st.session_state["results"] = None
        with st.spinner("Fetching seed details..."):
            try:
                seed = cached_detail(seed_stub.id)
            except Exception as exc:
                st.error(f"Failed to fetch seed detail: {exc}")
                return

        progress_bar = st.progress(0.0, text="Gathering candidates...")

        def on_progress(done: int, total: int) -> None:
            frac = done / total if total else 1.0
            progress_bar.progress(min(frac, 1.0), text=f"Analyzing candidates ({done}/{total})...")

        try:
            results = candidates.run_match_pipeline(
                seed, result_count=config.RESULT_COUNT, progress_callback=on_progress
            )
        except Exception as exc:
            st.error(f"Matching failed: {exc}")
            return
        progress_bar.empty()

        st.session_state["results"] = results
        st.session_state["seed"] = seed

    results = st.session_state.get("results")
    seed = st.session_state.get("seed")
    if not results:
        return

    st.success(f"Seed: **{seed.title}** — {seed.artist_name}")
    if len(results) < config.RESULT_COUNT:
        st.info(
            f"Only {len(results)}/{config.RESULT_COUNT} candidates passed filtering "
            "for this seed -- showing what fit rather than padding with poor matches."
        )

    # Explain only the top 3 by score, in one batched call -- Groq's free
    # tier has a per-minute token cap, and prose for all 20 isn't useful.
    explain_key = f"explanations_{seed.id}"
    if explain_key not in st.session_state:
        top3 = sorted(results, key=lambda r: r.breakdown.total, reverse=True)[:3]
        top3_payload = [
            (
                r.track.title,
                {
                    "bpm": r.breakdown.bpm,
                    "key": r.breakdown.key,
                    "tags": r.breakdown.tags,
                    "genre": r.breakdown.genre,
                    "energy": r.breakdown.energy,
                },
            )
            for r in top3
        ]
        st.session_state[explain_key] = groq_agent.explain_top_results(seed.title, top3_payload)
    explanations = st.session_state[explain_key]

    if not config.GROQ_ENABLED:
        st.caption("Groq disabled (no GROQ_API_KEY) -- showing templated explanations for the top 3.")

    sort_by = st.radio("Sort by", ["score", "bpm", "key"], horizontal=True)
    rows = results
    if sort_by == "bpm":
        rows = sorted(rows, key=lambda r: r.breakdown.bpm or 0, reverse=True)
    elif sort_by == "key":
        rows = sorted(rows, key=lambda r: r.breakdown.key or 0, reverse=True)

    for i, r in enumerate(rows, 1):
        with st.container(border=True):
            cols = st.columns([3, 1, 1, 1, 1, 1, 2])
            cols[0].markdown(f"**{i}. {r.track.title}** — {r.track.artist_name}")
            cols[1].metric("Score", f"{r.breakdown.total:.2f}")
            cols[2].write(f"BPM: {r.breakdown.bpm or '—'}")
            cols[3].write(f"Key: {r.breakdown.key or '—'}")
            cols[4].write(f"Genre: {r.breakdown.genre or '—'}")
            cols[5].write(r.breakdown.label)
            with cols[6]:
                _preview_player(r.track.id)
            if r.track.title in explanations:
                st.caption(explanations[r.track.title])


def render_pair_mode() -> None:
    st.subheader("Score a hand-picked pair")
    col1, col2 = st.columns(2)
    with col1:
        track_a_stub = _search_and_select("Song A", "pair_a")
    with col2:
        track_b_stub = _search_and_select("Song B", "pair_b")

    if track_a_stub is None or track_b_stub is None:
        return

    if st.button("Score pair", type="primary"):
        with st.spinner("Analyzing both tracks..."):
            try:
                track_a = cached_detail(track_a_stub.id)
                track_b = cached_detail(track_b_stub.id)
                breakdown = candidates.score_pair(track_a, track_b)
            except Exception as exc:
                st.error(f"Scoring failed: {exc}")
                return
        st.session_state["pair_result"] = (track_a, track_b, breakdown)

    result = st.session_state.get("pair_result")
    if not result:
        return
    track_a, track_b, breakdown = result
    st.success(f"**{track_a.title}** vs **{track_b.title}**")
    st.metric("Total score", f"{breakdown.total:.2f}", breakdown.label)
    st.write(
        {
            "bpm": breakdown.bpm,
            "key": breakdown.key,
            "tags": breakdown.tags,
            "genre": breakdown.genre,
            "energy": breakdown.energy,
        }
    )


def main() -> None:
    st.title("🎧 Cue.ai — DJ matching assistant")
    mode = st.radio("Mode", ["Find matches", "Score a pair"], horizontal=True)
    if mode == "Find matches":
        render_find_matches()
    else:
        render_pair_mode()


if __name__ == "__main__":
    main()

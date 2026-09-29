"""Manual verification script for Stage 5 (not a pytest file).

Run: python tests/verify_stage5.py
Given a seed, builds a deduped candidate pool, hard-filters by BPM, lazily
analyzes/scores/ranks, and prints the top RESULT_COUNT with a breakdown.
Also times a repeat run on the same seed to show caching makes it faster.

Honesty note: without a LASTFM_API_KEY set in .env, candidate discovery
falls back to Deezer-only sources (related artists + global chart), which
is exactly the documented degraded path in sources/lastfm.py. The pool may
land under the 100-200 target in that case -- this script reports the
real pool size rather than pretending otherwise.
"""
import time

import config
from db import repo
from matching import candidates
from sources import deezer

SEED_QUERY = "One More Time Daft Punk"


def main() -> None:
    repo.init_db()
    if not config.LASTFM_API_KEY:
        print("[note] LASTFM_API_KEY not set -- running Deezer-only candidate discovery.\n")

    seed_hit = deezer.search_tracks(SEED_QUERY, limit=1)[0]
    seed = deezer.get_track_detail(seed_hit.id)
    print(f"Seed: {seed.title} - {seed.artist_name} (id={seed.id}, deezer_bpm={seed.bpm})")

    pool = candidates.gather_candidate_pool(seed)
    print(f"Raw deduped pool size: {len(pool)}")

    filtered = candidates.hard_filter_bpm(seed.bpm, pool)
    print(f"After BPM hard filter: {len(filtered)}")

    print("\n--- First run (cold cache for these candidates) ---")
    t0 = time.monotonic()
    results = candidates.run_match_pipeline(seed, result_count=config.RESULT_COUNT)
    t1 = time.monotonic()
    print(f"Ranked {len(results)} results in {t1 - t0:.1f}s")

    print(f"\n{'#':<3}{'title':<40}{'artist':<20}{'total':>7}  label")
    for i, r in enumerate(results, 1):
        print(
            f"{i:<3}{r.track.title[:38]:<40}{r.track.artist_name[:18]:<20}"
            f"{r.breakdown.total:>7.3f}  {r.breakdown.label}"
        )

    print("\n--- Second run on the same seed (should be faster: analysis is cached) ---")
    t2 = time.monotonic()
    candidates.run_match_pipeline(seed, result_count=config.RESULT_COUNT)
    t3 = time.monotonic()
    print(f"Repeat run: {t3 - t2:.1f}s (first run was {t1 - t0:.1f}s)")

    if len(results) < config.RESULT_COUNT:
        print(
            f"\n[honest note] Only {len(results)}/{config.RESULT_COUNT} candidates passed "
            "filtering -- returning fewer rather than padding with poor matches."
        )


if __name__ == "__main__":
    main()

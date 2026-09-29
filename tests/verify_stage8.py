"""Manual verification script for Stage 8 (not a pytest file).

Run: python tests/verify_stage8.py
Runs the full pipeline on 10 seeds spanning different genres/BPMs, times
each run, and prints a usability summary (score distribution, safe vs
adventurous split, diversity) so results can be judged honestly rather
than just asserted. Also demonstrates a warm-cache repeat run's timing.
"""
import time

from db import repo
from matching import candidates
from sources import deezer

TEST_SEEDS = [
    "One More Time Daft Punk",
    "Levels Avicii",
    "Blinding Lights The Weeknd",
    "Billie Jean Michael Jackson",
    "Sandstorm Darude",
    "Bad Guy Billie Eilish",
    "Uptown Funk Bruno Mars",
    "Take On Me a-ha",
    "Rolling in the Deep Adele",
    "Shape of You Ed Sheeran",
]


def main() -> None:
    repo.init_db()
    summary = []

    for query in TEST_SEEDS:
        hits = deezer.search_tracks(query, limit=1)
        if not hits:
            print(f"[skip] no match for {query}")
            continue
        seed = deezer.get_track_detail(hits[0].id)

        t0 = time.monotonic()
        results = candidates.run_match_pipeline(seed)
        elapsed = time.monotonic() - t0

        safe = sum(1 for r in results if r.breakdown.label == "safe")
        adventurous = len(results) - safe
        artists = {r.track.artist_id for r in results}
        avg_score = sum(r.breakdown.total for r in results) / len(results) if results else 0.0

        summary.append(
            {
                "seed": f"{seed.title} - {seed.artist_name}",
                "count": len(results),
                "elapsed": elapsed,
                "avg_score": avg_score,
                "top_score": results[0].breakdown.total if results else 0.0,
                "safe": safe,
                "adventurous": adventurous,
                "unique_artists": len(artists),
            }
        )
        print(f"{seed.title} - {seed.artist_name}: {len(results)} results in {elapsed:.1f}s, "
              f"top={results[0].breakdown.total:.2f}, avg={avg_score:.2f}, "
              f"safe={safe}, adventurous={adventurous}, unique_artists={len(artists)}")

    print("\n--- Summary ---")
    n = len(summary)
    if n == 0:
        print("No seeds produced results.")
        return
    avg_count = sum(s["count"] for s in summary) / n
    avg_top = sum(s["top_score"] for s in summary) / n
    avg_time = sum(s["elapsed"] for s in summary) / n
    print(f"Seeds tested: {n}")
    print(f"Average result count: {avg_count:.1f}/20")
    print(f"Average top score: {avg_top:.2f}")
    print(f"Average runtime per seed: {avg_time:.1f}s")
    usable = sum(1 for s in summary if s["count"] >= 15 and s["top_score"] >= 0.6)
    print(f"Seeds meeting a basic usability bar (>=15 results, top score >=0.6): {usable}/{n}")


if __name__ == "__main__":
    main()

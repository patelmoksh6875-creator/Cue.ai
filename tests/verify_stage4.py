"""Manual verification script for Stage 4 (not a pytest file).

Run: python tests/verify_stage4.py
Scores two hand-picked, real tracks end to end (Deezer detail + librosa
analysis + Last.fm-style tags stubbed) and prints a readable breakdown.
"""
from db import repo
from sources import deezer
from analysis import audio
from matching import scoring

# Two house/electronic tracks that should mix reasonably well.
SEED_QUERY = "One More Time Daft Punk"
CANDIDATE_QUERY = "Get Lucky Daft Punk"


def _analyze(query: str) -> dict:
    hit = deezer.search_tracks(query, limit=1)[0]
    detail = deezer.get_track_detail(hit.id)
    preview = deezer.get_fresh_preview_url(hit.id)
    result = audio.analyze_preview(preview, deezer_bpm=detail.bpm)
    return {
        "title": detail.title,
        "artist": detail.artist_name,
        "genre": detail.genre,
        "bpm": result.bpm,
        "camelot": result.camelot,
        "energy": result.energy,
        "tags": {"french house", "dance", "electronic"},  # stand-in until Stage 5 wires Last.fm
    }


def main() -> None:
    repo.init_db()
    seed = _analyze(SEED_QUERY)
    candidate = _analyze(CANDIDATE_QUERY)

    print(f"Seed:      {seed['title']} - {seed['artist']} "
          f"({seed['bpm']:.1f} BPM, {seed['camelot']}, energy={seed['energy']:.2f})")
    print(f"Candidate: {candidate['title']} - {candidate['artist']} "
          f"({candidate['bpm']:.1f} BPM, {candidate['camelot']}, energy={candidate['energy']:.2f})")

    bpm = scoring.bpm_score(seed["bpm"], candidate["bpm"])
    key = scoring.key_score(seed["camelot"], candidate["camelot"])
    tags = scoring.tags_score(seed["tags"], candidate["tags"])
    genre = scoring.genre_score(seed["genre"], candidate["genre"])
    energy = scoring.energy_score(seed["energy"], candidate["energy"])
    breakdown = scoring.total_score(bpm=bpm, key=key, tags=tags, genre=genre, energy=energy)

    print("\nScore breakdown:")
    print(f"  bpm:    {breakdown.bpm}")
    print(f"  key:    {breakdown.key}")
    print(f"  tags:   {breakdown.tags}")
    print(f"  genre:  {breakdown.genre}")
    print(f"  energy: {breakdown.energy}")
    print(f"  TOTAL:  {breakdown.total}  ({breakdown.label})")


if __name__ == "__main__":
    main()

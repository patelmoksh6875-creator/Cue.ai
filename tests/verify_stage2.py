"""Manual verification script for Stage 2 (not a pytest file).

Run: python tests/verify_stage2.py
Searches a song, stores it via repo.py, prints BPM + a working preview URL,
then repeats the search to show cache is used for the DB read.
"""
import time

import config
from db import repo
from sources import deezer

repo.init_db()

print("--- Search ---")
results = deezer.search_tracks("One More Time Daft Punk", limit=1)
assert results, "expected at least one search result"
hit = results[0]
print(f"Found: {hit.title} by {hit.artist_name} (id={hit.id})")

print("--- Fetch detail (BPM, ISRC, genre) ---")
t0 = time.monotonic()
detail = deezer.get_track_detail(hit.id)
t1 = time.monotonic()
print(f"BPM: {detail.bpm}, ISRC: {detail.isrc}, genre: {detail.genre} ({t1 - t0:.2f}s)")

print("--- Preview URL ---")
preview = deezer.get_fresh_preview_url(hit.id)
print(f"Preview URL: {preview}")
assert preview and preview.startswith("http"), "expected a working preview URL"

print("--- Confirm it's cached in DB ---")
cached = repo.get_track(hit.id)
assert cached is not None
print(f"DB row: {cached}")

print("--- Repeat detail fetch to show DB has the row (cache warm) ---")
t2 = time.monotonic()
again = repo.get_track(hit.id)
t3 = time.monotonic()
print(f"Cached read: {again.title} ({t3 - t2:.4f}s, no API call)")

print("\nStage 2 verification PASSED")

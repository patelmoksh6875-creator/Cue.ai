"""Regression tests for server/routes/*.py using FastAPI's TestClient --
no real network calls, no real server process."""
import pytest
from fastapi.testclient import TestClient

from db import repo
from server.main import app
from sources import deezer


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.sqlite3"
    repo.init_db(db_path)
    monkeypatch.setattr(repo.config, "DB_PATH", db_path)


@pytest.fixture()
def client():
    return TestClient(app)


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_search_empty_query_returns_empty_list(client):
    resp = client.get("/api/search", params={"q": ""})
    assert resp.status_code == 200
    assert resp.json() == []


def test_search_happy_path(client, monkeypatch):
    def fake_search(query, limit=10):
        return [deezer.DeezerTrack(
            id=1, title="Test Song", artist_id=10, artist_name="Test Artist",
            album_id=20, duration=200, bpm=128.0, isrc="ABC123",
        )]

    monkeypatch.setattr(deezer, "search_tracks", fake_search)
    resp = client.get("/api/search", params={"q": "test"})
    assert resp.status_code == 200
    assert resp.json() == [{"id": 1, "title": "Test Song", "artist": "Test Artist"}]


def test_search_returns_specific_error_on_deezer_failure(client, monkeypatch):
    """Regression test: server/routes/search.py previously had NO
    exception handling at all (unlike match.py/preview.py, which already
    caught DeezerAPIError), so a real Deezer outage/rate-limit surfaced
    as FastAPI's generic 500 instead of a specific, actionable message --
    reproduced directly against sources.deezer.search_tracks (confirmed
    it raises DeezerAPIError after retries against an unreachable host)
    before this test was written."""

    def fake_search(query, limit=10):
        raise deezer.DeezerAPIError("Deezer is unreachable after 3 retries on /search")

    monkeypatch.setattr(deezer, "search_tracks", fake_search)
    resp = client.get("/api/search", params={"q": "test"})
    assert resp.status_code == 502
    assert "unreachable" in resp.json()["detail"].lower()


def test_search_rejects_missing_query_param(client):
    resp = client.get("/api/search")
    assert resp.status_code == 422


def test_match_returns_specific_error_on_deezer_failure(client, monkeypatch):
    def fake_get_track_detail(track_id):
        raise deezer.DeezerAPIError("simulated failure")

    monkeypatch.setattr(deezer, "get_track_detail", fake_get_track_detail)
    resp = client.post("/api/match", json={"seed_id": 999})
    assert resp.status_code == 502


def test_preview_404_when_no_preview_available(client, monkeypatch):
    monkeypatch.setattr(deezer, "get_fresh_preview_url", lambda track_id: None)
    resp = client.get("/api/preview/123")
    assert resp.status_code == 404


def test_mix_snippet_unknown_style_returns_error(client, monkeypatch):
    resp = client.post(
        "/api/mix-snippet",
        json={"a_id": 1, "b_id": 2, "style": "nonexistent-style", "length_seconds": 12},
    )
    # Cache miss path starts a job; poll it to see the style validation error.
    job_id = resp.json()["job_id"]
    assert job_id is not None
    import time

    for _ in range(20):
        poll = client.get(f"/api/mix-snippet/{job_id}").json()
        if poll["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert poll["status"] == "error"
    assert "Unknown style" in poll["error"]


def test_refine_match_rejects_empty_term(client):
    resp = client.post("/api/match/refine", json={"seed_id": 1, "term": "   "})
    assert resp.status_code == 400


def test_refine_match_returns_specific_error_on_deezer_failure(client, monkeypatch):
    def fake_get_track_detail(track_id):
        raise deezer.DeezerAPIError("simulated failure")

    monkeypatch.setattr(deezer, "get_track_detail", fake_get_track_detail)
    resp = client.post("/api/match/refine", json={"seed_id": 999, "term": "house"})
    assert resp.status_code == 502


def test_refine_match_happy_path(client, monkeypatch):
    import time

    seed = deezer.DeezerTrack(
        id=1, title="Seed", artist_id=10, artist_name="Seed Artist",
        album_id=20, duration=200, bpm=128.0, isrc="AAA",
    )
    monkeypatch.setattr(deezer, "get_track_detail", lambda track_id: seed)
    monkeypatch.setattr(
        "matching.candidates.refine_candidates",
        lambda seed, term, result_count=60, progress_callback=None: [],
    )
    resp = client.post("/api/match/refine", json={"seed_id": 1, "term": "house"})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    for _ in range(20):
        poll = client.get(f"/api/match/{job_id}").json()
        if poll["status"] in ("done", "error"):
            break
        time.sleep(0.1)
    assert poll["status"] == "done"
    assert poll["result"]["term"] == "house"
    assert poll["result"]["results"] == []


def test_mix_snippet_rejects_unknown_source(client):
    resp = client.post("/api/mix-snippet", json={"a_id": 1, "b_id": 2, "source": "vocals_only"})
    assert resp.status_code == 400


def test_mix_snippet_cache_hit_returns_full_contract(client, tmp_path, monkeypatch):
    from mixing import render
    import json

    monkeypatch.setattr(render, "SNIPPET_DIR", tmp_path)
    key = render.snippet_cache_key(1, 2, "blend", 12, "auto", 0)
    (tmp_path / f"{key}.mp3").write_bytes(b"x")
    (tmp_path / f"{key}.json").write_text(json.dumps({"a": {}, "b": {}, "windows": [], "window_rank": 0, "note": "n"}))
    body = client.post("/api/mix-snippet", json={"a_id": 1, "b_id": 2}).json()
    assert body["job_id"] is None
    assert body["snippet_url"] == f"/api/snippet/{key}.mp3"
    assert {"a", "b", "windows", "window_rank", "note"} <= set(body)


def test_static_files_are_served_no_cache(client):
    assert client.get("/").headers.get("cache-control") == "no-cache"
    assert client.get("/app.js").headers.get("cache-control") == "no-cache"

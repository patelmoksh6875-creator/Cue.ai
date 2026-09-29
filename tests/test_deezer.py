"""Mocked adapter tests -- no real network calls. Verifies normalization,
persistence, throttling, and error handling in isolation."""
import httpx
import pytest

from db import repo
from sources import deezer


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.sqlite3"
    repo.init_db(db_path)
    monkeypatch.setattr(repo.config, "DB_PATH", db_path)
    yield


def _mock_transport(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url=deezer.config.DEEZER_BASE_URL)


def test_search_tracks_normalizes_results(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": 1,
                        "title": "Test Song",
                        "duration": 200,
                        "isrc": "ABC123",
                        "bpm": 128.0,
                        "artist": {"id": 10, "name": "Test Artist"},
                        "album": {"id": 20, "title": "Test Album"},
                    }
                ]
            },
        )

    monkeypatch.setattr(deezer, "_client", _mock_transport(handler))
    results = deezer.search_tracks("test query")
    assert len(results) == 1
    assert results[0].title == "Test Song"
    assert results[0].artist_name == "Test Artist"
    assert results[0].bpm == 128.0


def test_get_track_detail_persists_via_repo(monkeypatch):
    def handler(request):
        if "/album/" in str(request.url):
            return httpx.Response(200, json={"title": "Test Album", "genres": {"data": [{"name": "House"}]}})
        return httpx.Response(
            200,
            json={
                "id": 1,
                "title": "Test Song",
                "duration": 200,
                "isrc": "ABC123",
                "bpm": 128.0,
                "artist": {"id": 10, "name": "Test Artist"},
                "album": {"id": 20, "title": "Test Album"},
            },
        )

    monkeypatch.setattr(deezer, "_client", _mock_transport(handler))
    track = deezer.get_track_detail(1)
    assert track.genre == "House"

    stored = repo.get_track(1)
    assert stored is not None
    assert stored.title == "Test Song"
    assert stored.deezer_bpm == 128.0


def test_get_track_detail_missing_bpm_stores_none(monkeypatch):
    def handler(request):
        if "/album/" in str(request.url):
            return httpx.Response(200, json={"title": "Album", "genres": {"data": []}})
        return httpx.Response(
            200,
            json={
                "id": 2,
                "title": "No BPM Song",
                "duration": 180,
                "isrc": None,
                "bpm": 0,
                "artist": {"id": 11, "name": "Artist"},
                "album": {"id": 21, "title": "Album"},
            },
        )

    monkeypatch.setattr(deezer, "_client", _mock_transport(handler))
    track = deezer.get_track_detail(2)
    assert track.bpm is None
    assert track.genre is None


def test_deezer_api_error_on_error_response(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"error": {"type": "OAuthException", "message": "bad"}})

    monkeypatch.setattr(deezer, "_client", _mock_transport(handler))
    with pytest.raises(deezer.DeezerAPIError):
        deezer.search_tracks("anything")


def test_deezer_raises_clear_error_after_retries_exhausted(monkeypatch):
    def handler(request):
        return httpx.Response(500)

    monkeypatch.setattr(deezer, "_client", _mock_transport(handler))
    monkeypatch.setattr(deezer.time, "sleep", lambda _: None)  # skip real backoff delay
    with pytest.raises(deezer.DeezerAPIError, match="failed after"):
        deezer.search_tracks("anything")


def test_get_fresh_preview_url_returns_none_when_absent(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"id": 3, "title": "No Preview"})

    monkeypatch.setattr(deezer, "_client", _mock_transport(handler))
    url = deezer.get_fresh_preview_url(3)
    assert url is None


def test_get_album_genre_uses_cache_when_present(monkeypatch):
    repo.upsert_album(repo.Album(id=99, title="Cached Album", genre="Techno"))
    call_count = {"n": 0}

    def handler(request):
        call_count["n"] += 1
        return httpx.Response(200, json={"title": "Cached Album", "genres": {"data": [{"name": "House"}]}})

    monkeypatch.setattr(deezer, "_client", _mock_transport(handler))
    genre = deezer.get_album_genre(99)
    assert genre == "Techno"
    assert call_count["n"] == 0  # never hit the (mocked) API

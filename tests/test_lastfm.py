"""Mocked adapter tests -- no real network calls."""
import httpx
import pytest

from sources import lastfm


def _mock_transport(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url=lastfm.config.LASTFM_BASE_URL)


def test_get_top_tags_raises_not_configured_without_key(monkeypatch):
    monkeypatch.setattr(lastfm.config, "LASTFM_API_KEY", "")
    with pytest.raises(lastfm.LastFMNotConfigured):
        lastfm.get_top_tags("Artist", "Title")


def test_get_top_tags_normalizes_weights(monkeypatch):
    monkeypatch.setattr(lastfm.config, "LASTFM_API_KEY", "fake-key")

    def handler(request):
        return httpx.Response(
            200,
            json={
                "toptags": {
                    "tag": [
                        {"name": "house", "count": 100},
                        {"name": "dance", "count": 50},
                    ]
                }
            },
        )

    monkeypatch.setattr(lastfm, "_client", _mock_transport(handler))
    tags = lastfm.get_top_tags("Artist", "Title")
    assert tags[0] == ("house", 1.0)
    assert tags[1] == ("dance", 0.5)


def test_get_top_tags_empty_when_no_tags(monkeypatch):
    monkeypatch.setattr(lastfm.config, "LASTFM_API_KEY", "fake-key")

    def handler(request):
        return httpx.Response(200, json={"toptags": {"tag": []}})

    monkeypatch.setattr(lastfm, "_client", _mock_transport(handler))
    tags = lastfm.get_top_tags("Obscure Artist", "Obscure Title")
    assert tags == []


def test_get_similar_tracks_normalizes(monkeypatch):
    monkeypatch.setattr(lastfm.config, "LASTFM_API_KEY", "fake-key")

    def handler(request):
        return httpx.Response(
            200,
            json={
                "similartracks": {
                    "track": [
                        {"name": "Similar Song", "artist": {"name": "Similar Artist"}, "match": "0.9"}
                    ]
                }
            },
        )

    monkeypatch.setattr(lastfm, "_client", _mock_transport(handler))
    similar = lastfm.get_similar_tracks("Artist", "Title")
    assert similar[0].title == "Similar Song"
    assert similar[0].artist == "Similar Artist"
    assert similar[0].match == 0.9


def test_lastfm_error_response_raises(monkeypatch):
    monkeypatch.setattr(lastfm.config, "LASTFM_API_KEY", "fake-key")

    def handler(request):
        return httpx.Response(200, json={"error": 6, "message": "Track not found"})

    monkeypatch.setattr(lastfm, "_client", _mock_transport(handler))
    with pytest.raises(lastfm.LastFMError):
        lastfm.get_top_tags("Artist", "Title")


def test_lastfm_raises_clear_error_after_retries_exhausted(monkeypatch):
    monkeypatch.setattr(lastfm.config, "LASTFM_API_KEY", "fake-key")

    def handler(request):
        return httpx.Response(500)

    monkeypatch.setattr(lastfm, "_client", _mock_transport(handler))
    monkeypatch.setattr(lastfm.time, "sleep", lambda _: None)
    with pytest.raises(lastfm.LastFMError, match="failed after"):
        lastfm.get_top_tags("Artist", "Title")

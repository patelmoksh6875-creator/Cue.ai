"""These tests run entirely offline. Since this session has no
GROQ_API_KEY, config.GROQ_ENABLED is False and every call below exercises
the real deterministic fallback path (not a mock standing in for it).
"""
from agent import groq_agent


def test_expand_vibe_query_falls_back_without_key():
    result = groq_agent.expand_vibe_query("summer beach house vibe")
    assert result.queries == ["summer beach house vibe"]
    assert "summer" in result.tags
    assert "beach" in result.tags


def test_expand_vibe_query_filters_short_words():
    result = groq_agent.expand_vibe_query("a to be it")
    assert result.tags == []


def test_explain_top_results_falls_back_without_key():
    top = [
        ("Wide Open", {"bpm": 0.98, "key": 1.0}),
        ("RATATA", {"bpm": 0.95, "key": 0.85}),
    ]
    explanations = groq_agent.explain_top_results("One More Time", top)
    assert set(explanations) == {"Wide Open", "RATATA"}
    assert "Wide Open" in explanations["Wide Open"]
    assert "One More Time" in explanations["Wide Open"]


def test_get_client_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(config_module(), "GROQ_ENABLED", False)
    assert groq_agent._get_client() is None


def config_module():
    import config

    return config


def test_call_with_fallback_returns_none_when_no_client(monkeypatch):
    monkeypatch.setattr(groq_agent, "_get_client", lambda: None)
    result = groq_agent._call_with_fallback(lambda: [], max_tokens=10)
    assert result is None


class _FakeChoice:
    def __init__(self, content):
        self.message = type("M", (), {"content": content})


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content=None, raise_error=False):
        self._content = content
        self._raise = raise_error

    def create(self, **kwargs):
        if self._raise:
            raise RuntimeError("simulated 429")
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    def __init__(self, content=None, raise_error=False):
        self.chat = _FakeChat(_FakeCompletions(content, raise_error))


def test_call_with_fallback_uses_first_working_model(monkeypatch):
    monkeypatch.setattr(groq_agent, "_get_client", lambda: _FakeClient(content="hello"))
    monkeypatch.setattr(groq_agent, "_refresh_available_models", lambda: ["model-a", "model-b"])
    result = groq_agent._call_with_fallback(lambda: [{"role": "user", "content": "hi"}], max_tokens=10)
    assert result == "hello"


def test_call_with_fallback_all_models_fail_returns_none(monkeypatch):
    monkeypatch.setattr(groq_agent, "_get_client", lambda: _FakeClient(raise_error=True))
    monkeypatch.setattr(groq_agent, "_refresh_available_models", lambda: ["model-a", "model-b"])
    result = groq_agent._call_with_fallback(lambda: [], max_tokens=10)
    assert result is None


def test_expand_vibe_query_parses_valid_groq_json(monkeypatch):
    content = '{"queries": ["deep house summer"], "tags": ["house", "chill"]}'
    monkeypatch.setattr(groq_agent, "_call_with_fallback", lambda *a, **k: content)
    result = groq_agent.expand_vibe_query("summer vibe")
    assert result.queries == ["deep house summer"]
    assert result.tags == ["house", "chill"]


def test_expand_vibe_query_falls_back_on_malformed_json(monkeypatch):
    monkeypatch.setattr(groq_agent, "_call_with_fallback", lambda *a, **k: "not json")
    result = groq_agent.expand_vibe_query("summer vibe")
    assert result.queries == ["summer vibe"]


def test_cheap_model_used_when_offered(monkeypatch):
    monkeypatch.setattr(groq_agent, "_offered_models", lambda: {config_module().GROQ_MODEL_CHEAP})
    assert groq_agent._cheap_model_if_available() == [config_module().GROQ_MODEL_CHEAP]


def test_cheap_model_falls_back_to_ordered_chain_when_deprecated(monkeypatch):
    monkeypatch.setattr(groq_agent, "_offered_models", lambda: {config_module().GROQ_MODEL_PRIMARY})
    monkeypatch.setattr(groq_agent, "_refresh_available_models", lambda: [config_module().GROQ_MODEL_PRIMARY])
    assert groq_agent._cheap_model_if_available() == [config_module().GROQ_MODEL_PRIMARY]


def test_expand_vibe_query_requests_cheap_model(monkeypatch):
    captured = {}

    def fake_call_with_fallback(build_messages, max_tokens, models=None):
        captured["models"] = models
        return None

    monkeypatch.setattr(groq_agent, "_call_with_fallback", fake_call_with_fallback)
    monkeypatch.setattr(groq_agent, "_cheap_model_if_available", lambda: ["cheap-model"])
    groq_agent.expand_vibe_query("summer vibe")
    assert captured["models"] == ["cheap-model"]

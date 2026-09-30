"""These tests exercise the real deterministic fallback path (not a mock
standing in for it) by forcing _get_client() to return None, regardless
of whether this environment has a real GROQ_API_KEY configured -- a
config-level patch (e.g. config.GROQ_ENABLED) wouldn't be enough on its
own since _get_client() is the actual gate every call goes through.
"""
import pytest

from agent import groq_agent


@pytest.fixture(autouse=True)
def _reset_groq_agent_module_caches():
    """groq_agent.py memoizes the client and the live model list in
    module-level globals (reasonable in production -- one process, one
    lookup), but that leaks between tests: a test that forces
    _get_client() to return None also, as a side effect of calling the
    real _offered_models()/_refresh_available_models(), caches an empty
    model list that then silently breaks later tests expecting the real
    API (e.g. making them look like they hit the deterministic fallback
    when they didn't really exercise the live path at all)."""
    groq_agent._client = None
    groq_agent._available_models = None
    groq_agent._offered_model_ids = None
    yield
    groq_agent._client = None
    groq_agent._available_models = None
    groq_agent._offered_model_ids = None


def test_expand_vibe_query_falls_back_without_key(monkeypatch):
    monkeypatch.setattr(groq_agent, "_get_client", lambda: None)
    result = groq_agent.expand_vibe_query("summer beach house vibe")
    assert result.queries == ["summer beach house vibe"]
    assert "summer" in result.tags
    assert "beach" in result.tags


def test_expand_vibe_query_filters_short_words(monkeypatch):
    monkeypatch.setattr(groq_agent, "_get_client", lambda: None)
    result = groq_agent.expand_vibe_query("a to be it")
    assert result.tags == []


def test_explain_top_results_falls_back_without_key(monkeypatch):
    monkeypatch.setattr(groq_agent, "_get_client", lambda: None)
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


@pytest.mark.skipif(not config_module().GROQ_ENABLED, reason="no GROQ_API_KEY configured")
def test_live_expand_vibe_query_returns_real_llm_output():
    """Regression test for a real bug: GROQ_MODEL_FALLBACK/CHEAP were
    deprecated by Groq (removed from the model lineup entirely), and
    separately max_tokens=200 was too small for gpt-oss-120b's output,
    truncating the JSON mid-string and silently falling back to the
    deterministic path. Only runs when a real key is configured."""
    result = groq_agent.expand_vibe_query("summer beach house vibe")
    # The deterministic fallback returns the input verbatim as the only
    # query; a real LLM call expands it into several different ones.
    assert len(result.queries) > 1
    assert result.queries != ["summer beach house vibe"]


@pytest.mark.skipif(not config_module().GROQ_ENABLED, reason="no GROQ_API_KEY configured")
def test_live_explain_top_results_returns_real_llm_output():
    top = [("Get Lucky", {"bpm": 0.9, "key": 0.85})]
    explanations = groq_agent.explain_top_results("One More Time", top)
    fallback = groq_agent._templated_explanation("One More Time", "Get Lucky", top[0][1])
    assert explanations["Get Lucky"] != fallback

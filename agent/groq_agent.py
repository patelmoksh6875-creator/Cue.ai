"""Groq tool-calling agent: turns a free-text vibe query into search
queries/tags, and writes a short explanation of why the top 3 results fit.

The LLM NEVER decides matches or overrides scores -- matching/scoring.py
already did that deterministically. This module only supplies query
expansion and prose. If Groq is unavailable (no key, rate limited, or a
model gets deprecated), every function here falls back to deterministic,
templated behavior so the pipeline works identically with Groq disabled.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

import config

try:
    from groq import Groq
except ImportError:  # groq is optional at import time too
    Groq = None  # type: ignore

_client: Optional["Groq"] = None
_offered_model_ids: Optional[set[str]] = None
_available_models: Optional[list[str]] = None


def _get_client() -> Optional["Groq"]:
    global _client
    if not config.GROQ_ENABLED or Groq is None:
        return None
    if _client is None:
        _client = Groq(api_key=config.GROQ_API_KEY)
    return _client


def _offered_models() -> set[str]:
    """Call Groq's list-models endpoint once per process, since Groq has
    deprecated models before without much notice."""
    global _offered_model_ids
    if _offered_model_ids is not None:
        return _offered_model_ids
    client = _get_client()
    if client is None:
        _offered_model_ids = set()
        return _offered_model_ids
    try:
        response = client.models.list()
        _offered_model_ids = {m.id for m in response.data}
    except Exception:
        # If we can't even list models, assume nothing is safely usable
        # and let the deterministic fallback handle everything.
        _offered_model_ids = set()
    return _offered_model_ids


def _refresh_available_models() -> list[str]:
    """The primary/fallback chain, filtered to models Groq still offers."""
    global _available_models
    if _available_models is not None:
        return _available_models
    offered = _offered_models()
    _available_models = [m for m in config.GROQ_MODELS_ORDERED if m in offered]
    return _available_models


def _cheap_model_if_available() -> list[str]:
    """The cheap 8B model, used for low-stakes query expansion -- falls
    back to the primary/fallback chain if it's been deprecated."""
    if config.GROQ_MODEL_CHEAP in _offered_models():
        return [config.GROQ_MODEL_CHEAP]
    return _refresh_available_models()


def _call_with_fallback(
    build_messages, max_tokens: int, models: Optional[list[str]] = None
) -> Optional[str]:
    """Try each configured model in order; fall back to None (deterministic
    path) if every model fails (rate limit, deprecation, or no client).
    `models` defaults to the primary/fallback chain; pass a specific model
    list (e.g. [GROQ_MODEL_CHEAP]) for smaller, lower-stakes tasks."""
    client = _get_client()
    if client is None:
        return None
    candidate_models = models if models is not None else _refresh_available_models()
    for model in candidate_models:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=build_messages(),
                max_tokens=max_tokens,
                temperature=0.3,
            )
            return resp.choices[0].message.content
        except Exception:
            continue  # 429, deprecated model, etc. -- try the next model
    return None


# --- Query expansion -------------------------------------------------------


@dataclass
class QueryExpansion:
    queries: list[str]
    tags: list[str]


def _deterministic_expand(vibe_text: str) -> QueryExpansion:
    """No-LLM fallback: naive keyword split, used verbatim as both the
    search query and the tag hints."""
    words = [w.strip().lower() for w in vibe_text.replace(",", " ").split() if len(w.strip()) > 2]
    return QueryExpansion(queries=[vibe_text], tags=words[:8])


def expand_vibe_query(vibe_text: str) -> QueryExpansion:
    """Turn free text like "summer beach vibe" into search queries and
    tag hints for candidate discovery. Uses the cheap model since this is
    a small, low-stakes task."""

    def build_messages():
        return [
            {
                "role": "system",
                "content": (
                    "You expand a DJ's vibe description into search queries and "
                    "music tags. Respond ONLY with compact JSON: "
                    '{"queries": ["..."], "tags": ["..."]}. 3-5 queries, 5-8 tags.'
                ),
            },
            {"role": "user", "content": vibe_text},
        ]

    raw = _call_with_fallback(build_messages, max_tokens=500, models=_cheap_model_if_available())
    if raw is None:
        return _deterministic_expand(vibe_text)

    try:
        data = json.loads(raw)
        queries = [str(q) for q in data.get("queries", [])][:5]
        tags = [str(t) for t in data.get("tags", [])][:8]
        if not queries:
            return _deterministic_expand(vibe_text)
        return QueryExpansion(queries=queries, tags=tags)
    except (json.JSONDecodeError, AttributeError, TypeError):
        return _deterministic_expand(vibe_text)


# --- Top-3 explanations ------------------------------------------------


def _templated_explanation(seed_title: str, candidate_title: str, breakdown: dict) -> str:
    bpm = breakdown.get("bpm")
    key = breakdown.get("key")
    parts = []
    if bpm is not None:
        parts.append(f"BPM match {bpm:.0%}")
    if key is not None:
        parts.append(f"key compatibility {key:.0%}")
    detail = ", ".join(parts) if parts else "overall vibe similarity"
    return f"{candidate_title} pairs with {seed_title} on {detail}."


def explain_top_results(
    seed_title: str, top_results: list[tuple[str, dict]]
) -> dict[str, str]:
    """One batched call explaining why the top N (typically 3) results
    fit the seed -- never one call per song, to stay well under Groq's
    free-tier per-minute token cap. `top_results` is [(title, breakdown_dict)].
    Falls back to a templated explanation per track if Groq is unavailable
    or returns something we can't parse."""
    fallback = {
        title: _templated_explanation(seed_title, title, breakdown)
        for title, breakdown in top_results
    }

    def build_messages():
        compact = [
            {"title": title, **{k: v for k, v in breakdown.items() if v is not None}}
            for title, breakdown in top_results
        ]
        return [
            {
                "role": "system",
                "content": (
                    "You are a DJ assistant. Given a seed track and a short list of "
                    "candidate tracks with their match scores, write one enthusiastic "
                    "sentence per candidate explaining why it mixes well. Respond ONLY "
                    'with compact JSON: {"<title>": "<one sentence>", ...}.'
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"seed": seed_title, "candidates": compact}),
            },
        ]

    raw = _call_with_fallback(build_messages, max_tokens=700)
    if raw is None:
        return fallback

    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return fallback
        # Only trust entries for titles we actually asked about.
        result = {title: data.get(title, fallback[title]) for title, _ in top_results}
        return result
    except json.JSONDecodeError:
        return fallback

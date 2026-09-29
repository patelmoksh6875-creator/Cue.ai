import pytest

from matching import scoring


# --- bpm_score -------------------------------------------------------------


def test_bpm_score_exact_match():
    assert scoring.bpm_score(128, 128) == 1.0


def test_bpm_score_within_tolerance_scores_high():
    score = scoring.bpm_score(128, 130)  # ~1.5% off
    assert 0.8 < score < 1.0


def test_bpm_score_far_off_scores_low():
    score = scoring.bpm_score(128, 200)
    assert score < 0.2


def test_bpm_score_double_time_scores_well():
    # 64 BPM candidate is double-time-compatible with a 128 BPM seed.
    score = scoring.bpm_score(128, 64)
    assert score > 0.9


def test_bpm_score_half_time_scores_well():
    score = scoring.bpm_score(64, 128)
    assert score > 0.9


def test_bpm_score_half_double_disabled():
    score = scoring.bpm_score(128, 64, half_double_matching=False)
    assert score < 0.2


def test_bpm_score_missing_bpm_returns_none():
    assert scoring.bpm_score(None, 128) is None
    assert scoring.bpm_score(128, None) is None
    assert scoring.bpm_score(0, 128) is None


# --- camelot_distance / key_score -------------------------------------------


def test_camelot_distance_identical():
    assert scoring.camelot_distance("8B", "8B") == 0


def test_camelot_distance_adjacent_same_letter():
    assert scoring.camelot_distance("8B", "9B") == 1
    assert scoring.camelot_distance("1B", "12B") == 1  # wraps around the wheel


def test_camelot_distance_relative_major_minor():
    assert scoring.camelot_distance("8B", "8A") == 1


def test_camelot_distance_far_apart():
    assert scoring.camelot_distance("1B", "7B") == 6


def test_camelot_distance_invalid_code():
    assert scoring.camelot_distance("13B", "8B") is None
    assert scoring.camelot_distance("garbage", "8B") is None


def test_key_score_identical():
    assert scoring.key_score("8B", "8B") == 1.0


def test_key_score_adjacent():
    assert scoring.key_score("8B", "9B") == 0.85


def test_key_score_far_defaults_low():
    assert scoring.key_score("1B", "7B") == config_default()


def config_default():
    from config import CAMELOT_DEFAULT_SCORE

    return CAMELOT_DEFAULT_SCORE


def test_key_score_missing_key_returns_none():
    assert scoring.key_score(None, "8B") is None
    assert scoring.key_score("8B", None) is None
    assert scoring.key_score("", "8B") is None


# --- tags_score --------------------------------------------------------


def test_tags_score_full_overlap():
    assert scoring.tags_score({"house", "dance"}, {"house", "dance"}) == 1.0


def test_tags_score_partial_overlap():
    score = scoring.tags_score({"house", "dance", "electronic"}, {"house", "pop"})
    assert 0.0 < score < 1.0


def test_tags_score_no_overlap():
    assert scoring.tags_score({"metal"}, {"jazz"}) == 0.0


def test_tags_score_missing_tags_returns_none():
    assert scoring.tags_score(set(), {"house"}) is None
    assert scoring.tags_score({"house"}, set()) is None
    assert scoring.tags_score(set(), set()) is None


def test_tags_score_case_insensitive():
    assert scoring.tags_score({"House"}, {"house"}) == 1.0


# --- genre_score -------------------------------------------------------


def test_genre_score_match():
    assert scoring.genre_score("Electronic", "electronic") == 1.0


def test_genre_score_mismatch():
    assert scoring.genre_score("Electronic", "Rock") == 0.0


def test_genre_score_missing_returns_none():
    assert scoring.genre_score(None, "Rock") is None
    assert scoring.genre_score("Rock", None) is None


# --- energy_score --------------------------------------------------------


def test_energy_score_identical():
    assert scoring.energy_score(0.5, 0.5) == 1.0


def test_energy_score_difference():
    assert scoring.energy_score(0.2, 0.8) == pytest.approx(0.4)


def test_energy_score_missing_returns_none():
    assert scoring.energy_score(None, 0.5) is None
    assert scoring.energy_score(0.5, None) is None


# --- total_score ---------------------------------------------------------


def test_total_score_all_components_present():
    result = scoring.total_score(bpm=1.0, key=1.0, tags=1.0, genre=1.0, energy=1.0)
    assert result.total == 1.0
    assert result.label == "safe"


def test_total_score_renormalizes_missing_components():
    # Only bpm and key present; total should equal a weighted avg of just those two.
    result = scoring.total_score(bpm=1.0, key=1.0, tags=None, genre=None, energy=None)
    assert result.total == 1.0


def test_total_score_missing_bpm_and_key_is_adventurous():
    result = scoring.total_score(bpm=None, key=None, tags=1.0, genre=1.0, energy=1.0)
    assert result.label == "adventurous"
    assert result.total == 1.0


def test_total_score_all_missing_is_zero():
    result = scoring.total_score(bpm=None, key=None, tags=None, genre=None, energy=None)
    assert result.total == 0.0
    assert result.label == "adventurous"


def test_total_score_weighted_partial_mix():
    result = scoring.total_score(bpm=0.5, key=None, tags=1.0, genre=None, energy=None)
    weights = __import__("config").SCORE_WEIGHTS
    expected = (weights["bpm"] * 0.5 + weights["tags"] * 1.0) / (weights["bpm"] + weights["tags"])
    assert result.total == pytest.approx(expected, abs=1e-4)

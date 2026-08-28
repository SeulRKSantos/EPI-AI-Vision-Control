"""Stage 4 tests: the compliance rule.

`evaluate_compliance` is the single point that decides whether a gate opens,
so it is tested exhaustively and without any infrastructure.
"""

import pytest

from app.db.models import AccessDecision
from app.schemas.messages import Detection
from app.services.access_control import evaluate_compliance

THRESHOLD = 0.60


def det(code: str, confidence: float = 0.95) -> Detection:
    return Detection(ppe_code=code, confidence=confidence)


# --- Granting --------------------------------------------------------------

def test_grants_when_every_required_item_is_detected():
    result = evaluate_compliance(
        {"helmet", "goggles"},
        [det("helmet"), det("goggles")],
        THRESHOLD,
    )
    assert result.granted
    assert result.decision is AccessDecision.GRANTED
    assert result.missing_ppe == []


def test_grants_when_extra_ppe_is_detected():
    """Wearing more than required is not a violation."""
    result = evaluate_compliance(
        {"helmet"},
        [det("helmet"), det("vest"), det("gloves")],
        THRESHOLD,
    )
    assert result.granted


def test_grants_when_role_requires_nothing():
    """An identified employee with no PPE requirement is allowed through."""
    result = evaluate_compliance(set(), [], THRESHOLD)
    assert result.granted


# --- Denying ---------------------------------------------------------------

def test_denies_and_names_the_missing_item():
    result = evaluate_compliance(
        {"helmet", "goggles", "gloves"},
        [det("helmet")],
        THRESHOLD,
    )
    assert not result.granted
    assert result.decision is AccessDecision.DENIED_MISSING_PPE
    assert result.missing_ppe == ["gloves", "goggles"]


def test_denies_when_nothing_is_detected():
    result = evaluate_compliance({"helmet"}, [], THRESHOLD)
    assert not result.granted
    assert result.missing_ppe == ["helmet"]


def test_missing_list_is_sorted_for_stable_output():
    """The firmware and the audit log both read this list; order must not vary."""
    result = evaluate_compliance({"vest", "boots", "helmet"}, [], THRESHOLD)
    assert result.missing_ppe == ["boots", "helmet", "vest"]


# --- Confidence threshold --------------------------------------------------

def test_low_confidence_detection_does_not_grant_access():
    """A weak guess must never be the reason a gate opens."""
    result = evaluate_compliance({"helmet"}, [det("helmet", 0.42)], THRESHOLD)
    assert not result.granted
    assert result.missing_ppe == ["helmet"]


def test_detection_exactly_at_threshold_is_accepted():
    result = evaluate_compliance({"helmet"}, [det("helmet", THRESHOLD)], THRESHOLD)
    assert result.granted


def test_detection_just_below_threshold_is_rejected():
    result = evaluate_compliance({"helmet"}, [det("helmet", THRESHOLD - 0.01)], THRESHOLD)
    assert not result.granted


@pytest.mark.parametrize("confidence", [0.0, 0.1, 0.59])
def test_various_low_confidences_are_rejected(confidence: float):
    result = evaluate_compliance({"helmet"}, [det("helmet", confidence)], THRESHOLD)
    assert not result.granted


def test_mixed_confidences_only_accept_the_strong_ones():
    result = evaluate_compliance(
        {"helmet", "gloves"},
        [det("helmet", 0.91), det("gloves", 0.30)],
        THRESHOLD,
    )
    assert not result.granted
    assert result.missing_ppe == ["gloves"]
    assert result.accepted_ppe == ["helmet"]


# --- Robustness ------------------------------------------------------------

def test_unknown_ppe_code_is_ignored_not_fatal():
    """A model class with no matching row must not break the decision."""
    result = evaluate_compliance(
        {"helmet"},
        [det("helmet"), det("some_unmapped_class")],
        THRESHOLD,
    )
    assert result.granted


def test_duplicate_detections_of_the_same_item_are_collapsed():
    """Two people in frame, or one item detected twice, must not confuse the rule."""
    result = evaluate_compliance(
        {"helmet"},
        [det("helmet", 0.80), det("helmet", 0.90)],
        THRESHOLD,
    )
    assert result.granted
    assert result.accepted_ppe == ["helmet"]


def test_duplicate_where_only_one_passes_threshold_still_grants():
    result = evaluate_compliance(
        {"helmet"},
        [det("helmet", 0.20), det("helmet", 0.95)],
        THRESHOLD,
    )
    assert result.granted


def test_a_stricter_threshold_denies_what_a_looser_one_grants():
    """The threshold is a policy knob; its effect must be real."""
    detections = [det("helmet", 0.70)]
    assert evaluate_compliance({"helmet"}, detections, 0.60).granted
    assert not evaluate_compliance({"helmet"}, detections, 0.85).granted


def test_result_is_immutable():
    """The decision must not be mutable after the fact."""
    result = evaluate_compliance({"helmet"}, [], THRESHOLD)
    with pytest.raises(Exception):
        result.decision = AccessDecision.GRANTED  # type: ignore[misc]

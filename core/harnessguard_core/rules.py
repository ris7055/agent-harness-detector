"""Rule-based baseline scorer (SPEC section 7.3).

Weighted sum of clear automation signals, squashed into [0, 1) with
``1 - exp(-sum)``. Used until a trained model exists, and kept as the
benchmark baseline. Returns ``(score, top_reasons)`` where each reason is
``{feature, value, contribution}`` sorted by contribution desc.
"""

from __future__ import annotations

import math
from typing import Any

MISSING = -1.0

# (feature, condition, weight). weight may be scaled by the feature value
# when scale=True. Conditions never fire on the -1 "missing" value.
_RULES: list[tuple[str, str, float, bool]] = [
    # feature            condition                 weight  scale_by_value
    ("fp_webdriver", "truthy", 0.60, False),
    ("fp_headless_ua", "truthy", 0.50, False),
    ("click_no_premove_ratio", ">=0.8", 0.40, True),
    ("click_center_offset_mean", "<0.1", 0.30, False),
    ("input_programmatic_ratio", ">=0.5", 0.50, True),
    ("key_interval_cv", "<0.15", 0.30, False),
    ("mouse_straightness_mean", ">0.97", 0.25, False),
]


def _fires(condition: str, v: float) -> bool:
    if v == MISSING:
        return False
    return {
        "truthy": v >= 0.5,
        ">=0.8": v >= 0.8,
        ">=0.5": v >= 0.5,
        "<0.1": 0.0 <= v < 0.1,
        "<0.15": 0.0 <= v < 0.15,
        ">0.97": v > 0.97,
    }[condition]


def score_rules(features: dict[str, float]) -> tuple[float, list[dict[str, Any]]]:
    """Score a feature dict; returns (probability-ish score, top reasons)."""
    total = 0.0
    reasons = []
    for name, condition, weight, scaled in _RULES:
        v = float(features.get(name, MISSING))
        if _fires(condition, v):
            contribution = weight * v if scaled else weight
            total += contribution
            reasons.append(
                {"feature": name, "value": v, "contribution": round(contribution, 4)}
            )
    reasons.sort(key=lambda r: r["contribution"], reverse=True)
    return 1.0 - math.exp(-total), reasons[:5]


def band_for_score(score: float, allow_below: float, block_above: float) -> str:
    """Score -> colour band (same thresholds as the allow/step_up/block bands)."""
    if score < allow_below:
        return "green"
    if score < block_above:
        return "amber"
    return "red"


def decision_for_score(score: float, allow_below: float, block_above: float) -> str:
    """Score -> decision band per SPEC 7.2 step 3."""
    if score < allow_below:
        return "allow"
    if score < block_above:
        return "step_up"
    return "block"

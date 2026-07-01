"""Deterministic off-map movement risk policy."""

from __future__ import annotations

from ..session.state import IllegalMoveRiskState

OFF_MAP_BASE_INCREMENT = 3
OFF_MAP_CONSECUTIVE_CAP = 2
OFF_MAP_DECAY_PER_SAFE_TURN = 1
OFF_MAP_MAX_ILLEGAL_VALUE = 20
OFF_MAP_WARNING_THRESHOLD = 2
OFF_MAP_MINOR_THRESHOLD = 4
OFF_MAP_MAJOR_THRESHOLD = 7
OFF_MAP_SEVERE_THRESHOLD = 10

OFF_MAP_THRESHOLDS_ASC: tuple[tuple[str, int], ...] = (
    ("warning", OFF_MAP_WARNING_THRESHOLD),
    ("minor_penalty", OFF_MAP_MINOR_THRESHOLD),
    ("major_penalty", OFF_MAP_MAJOR_THRESHOLD),
    ("severe_penalty", OFF_MAP_SEVERE_THRESHOLD),
)

OFF_MAP_THRESHOLDS_DESC: tuple[tuple[str, int], ...] = tuple(
    reversed(OFF_MAP_THRESHOLDS_ASC)
)


def off_map_next_consecutive_count(risk: IllegalMoveRiskState, *, turn_no: int) -> int:
    return risk.consecutive_count + 1 if risk.last_violation_turn == turn_no - 1 else 1


def off_map_increment(consecutive_count: int) -> int:
    return OFF_MAP_BASE_INCREMENT * (
        2 ** min(consecutive_count - 1, OFF_MAP_CONSECUTIVE_CAP)
    )


def off_map_penalty_tier(score: int) -> str:
    for tier, threshold in OFF_MAP_THRESHOLDS_DESC:
        if score >= threshold:
            return tier
    return "none"


def off_map_threshold_crossed(*, score_before: int, score_after: int) -> str:
    for tier, threshold in OFF_MAP_THRESHOLDS_DESC:
        if score_before < threshold <= score_after:
            return tier
    return ""


def off_map_threshold_value(tier: str) -> int | None:
    for threshold_tier, threshold in OFF_MAP_THRESHOLDS_ASC:
        if threshold_tier == tier:
            return threshold
    return None


def preview_off_map_risk_update(
    risk: IllegalMoveRiskState, *, turn_no: int
) -> dict[str, object]:
    score_before = risk.illegal_value
    consecutive_count = off_map_next_consecutive_count(risk, turn_no=turn_no)
    delta = off_map_increment(consecutive_count)
    score_after = min(score_before + delta, OFF_MAP_MAX_ILLEGAL_VALUE)
    penalty_tier = off_map_penalty_tier(score_after)
    threshold_crossed = off_map_threshold_crossed(
        score_before=score_before,
        score_after=score_after,
    )
    required_threshold = (
        off_map_threshold_value(penalty_tier)
        if penalty_tier in {"major_penalty", "severe_penalty"}
        else off_map_threshold_value(threshold_crossed)
    )

    return {
        "score_before": score_before,
        "score_after": score_after,
        "delta": delta,
        "consecutive_count": consecutive_count,
        "penalty_tier": penalty_tier,
        "threshold_crossed": threshold_crossed,
        "required_threshold": required_threshold,
        "heavy_punishment_required": penalty_tier
        in {"major_penalty", "severe_penalty"},
    }

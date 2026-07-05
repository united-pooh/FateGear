from __future__ import annotations

from scenario.ktsl.coupling import HIGH_COUPLING_THRESHOLD
from scenario.ktsl.evaluate import evaluate_fixture
from scenario.ktsl.fixtures import list_ktsl_fixtures


def test_schedule_layer_reduces_baseline_causal_violations() -> None:
    for fixture in list_ktsl_fixtures():
        baseline = evaluate_fixture(fixture, "baseline")
        schedule_only = evaluate_fixture(fixture, "schedule_only")

        assert baseline.metrics.causal_violation_count > 0
        assert schedule_only.metrics.causal_violation_count == 0
        assert schedule_only.metrics.barrier_wait_minutes > 0


def test_coupling_layer_reduces_high_coupling_drift_without_spotlight_regression() -> None:
    for fixture in list_ktsl_fixtures():
        schedule_only = evaluate_fixture(fixture, "schedule_only")
        ktsl_full = evaluate_fixture(fixture, "ktsl_full")

        assert schedule_only.metrics.high_coupling_time_drift_minutes > 0
        assert (
            ktsl_full.metrics.high_coupling_time_drift_minutes
            < schedule_only.metrics.high_coupling_time_drift_minutes
        )
        assert (
            ktsl_full.metrics.spotlight_max_gap_minutes
            <= schedule_only.metrics.spotlight_max_gap_minutes
        )
        assert any(
            decision.coupling_score >= HIGH_COUPLING_THRESHOLD
            and decision.drift_minutes > 0
            for decision in schedule_only.coupling_decisions
        )
        assert all(
            decision.drift_minutes == 0
            for decision in ktsl_full.coupling_decisions
            if decision.coupling_score >= HIGH_COUPLING_THRESHOLD
        )

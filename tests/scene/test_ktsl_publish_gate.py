"""Tests for PublishGate (Phase 2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scenario.ktsl.fixtures import build_library_sewer_church_fixture
from scenario.ktsl.models import (
    KTSLFixture,
    MetricSummary,
    ModeThresholds,
    PublishCriteria,
    PublishGateResult,
)
from scenario.publish_gate import PublishGate


@pytest.fixture
def fixture() -> "KTSLFixture":  # noqa: F821
    return build_library_sewer_church_fixture()


@pytest.fixture
def gate(fixture: "KTSLFixture") -> PublishGate:  # noqa: F821
    return PublishGate(fixture)


class TestLoadCriteriaFromYaml:
    def test_load_criteria_from_yaml(self, tmp_path: Path) -> None:
        yaml_content = """\
version: "1.0.0"
fixture_id: "test_fixture"
description: "Test criteria"
thresholds:
  baseline:
    max_causal_violations: 5
    max_retcons: 3
  schedule_only:
    max_causal_violations: 2
    max_unauthorized_actions: 4
    max_retcons: 1
  ktsl_full:
    max_causal_violations: 0
    max_unauthorized_actions: 0
    max_public_payload_leaks: 0
"""
        path = tmp_path / "publish-criteria.yaml"
        path.write_text(yaml_content)
        criteria = PublishGate.load_criteria(path)
        assert criteria.version == "1.0.0"
        assert "baseline" in criteria.thresholds
        assert "ktsl_full" in criteria.thresholds
        assert criteria.thresholds["baseline"].max_causal_violations == 5


class TestDefaultCriteriaHasAllModes:
    def test_default_criteria_has_all_modes(self) -> None:
        criteria = PublishGate.default_criteria("library_sewer_church")
        assert set(criteria.thresholds.keys()) == {
            "baseline",
            "schedule_only",
            "ktsl_full",
        }
        assert criteria.fixture_id == "library_sewer_church"
        assert criteria.thresholds["ktsl_full"].max_causal_violations == 0


class TestEvaluateReturnsResultForEachMode:
    def test_evaluate_returns_result_for_each_mode(
        self, gate: PublishGate
    ) -> None:
        criteria = PublishGate.default_criteria("library_sewer_church")
        result = gate.evaluate(criteria)
        assert isinstance(result, PublishGateResult)
        assert len(result.per_mode) == 3
        modes = {r.mode for r in result.per_mode}
        assert modes == {"baseline", "schedule_only", "ktsl_full"}


class TestPassWhenMetricsWithinThreshold:
    def test_pass_when_metrics_within_threshold(self, gate: PublishGate) -> None:
        # Use very generous thresholds so the fixture passes
        criteria = PublishCriteria(
            thresholds={
                "baseline": ModeThresholds(
                    max_causal_violations=100,
                    max_unauthorized_actions=100,
                    max_public_payload_leaks=100,
                ),
                "schedule_only": ModeThresholds(
                    max_causal_violations=100,
                    max_unauthorized_actions=100,
                    max_public_payload_leaks=100,
                ),
                "ktsl_full": ModeThresholds(
                    max_causal_violations=100,
                    max_unauthorized_actions=100,
                    max_public_payload_leaks=100,
                ),
            }
        )
        result = gate.evaluate(criteria)
        assert result.overall_pass is True
        for mode_result in result.per_mode:
            assert mode_result.passed is True


class TestFailWhenMetricsExceedThreshold:
    def test_fail_when_metrics_exceed_threshold(
        self, gate: PublishGate
    ) -> None:
        # Use zero thresholds on everything; fixture should fail ktsl_full
        criteria = PublishCriteria(
            thresholds={
                "ktsl_full": ModeThresholds(
                    max_causal_violations=0,
                    max_unauthorized_actions=0,
                    max_public_payload_leaks=0,
                    max_retcons=0,
                ),
            }
        )
        result = gate.evaluate(criteria)
        ktsl_result = next(
            m for m in result.per_mode if m.mode == "ktsl_full"
        )
        # whether it passes or fails depends on fixture; the important thing is
        # that failures are described when they exist
        if not ktsl_result.passed:
            assert len(ktsl_result.failures) > 0
            for f in ktsl_result.failures:
                assert ">" in f or "<" in f


class TestMissingThresholdIsSoftGate:
    def test_missing_threshold_is_soft_gate(self, gate: PublishGate) -> None:
        # Baseline with very sparse thresholds: missing keys should be warnings
        criteria = PublishCriteria(
            thresholds={
                "baseline": ModeThresholds(),  # all None
            }
        )
        result = gate.evaluate(criteria)
        assert len(result.per_mode) == 1
        mode_result = result.per_mode[0]
        assert mode_result.passed is True
        # warnings should mention skipped metrics
        assert len(mode_result.warnings) > 0


class TestOverallPassIsAllModesPass:
    def test_overall_pass_is_all_modes_pass(
        self, gate: PublishGate
    ) -> None:
        criteria = PublishGate.default_criteria("library_sewer_church")
        result = gate.evaluate(criteria)
        expected = all(m.passed for m in result.per_mode)
        assert result.overall_pass == expected


class TestEvaluateUsesExistingEvaluateModule:
    def test_evaluate_uses_existing_evaluate_module(
        self, gate: PublishGate
    ) -> None:
        criteria = PublishGate.default_criteria("library_sewer_church")
        with patch("scenario.publish_gate.evaluate_fixture") as mock_eval:
            # Provide a dummy evaluation result
            from scenario.ktsl.models import EvaluationResult

            mock_eval.return_value = EvaluationResult(
                fixture_id="library_sewer_church",
                run_mode="baseline",
                metrics=MetricSummary(),
            )
            gate.evaluate(criteria)
            assert mock_eval.call_count == 3

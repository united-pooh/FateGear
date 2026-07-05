"""Publish gate: load threshold criteria → run fixture evaluation → verdict."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ktsl.evaluate import evaluate_fixture
from .ktsl.models import (
    KTSLFixture,
    MetricSummary,
    ModeResult,
    ModeThresholds,
    PublishCriteria,
    PublishGateResult,
)


class PublishGate:
    """Run a fixture against publish criteria and produce a pass / fail verdict."""

    def __init__(self, fixture: KTSLFixture) -> None:
        self._fixture = fixture

    # ------------------------------------------------------------------
    @staticmethod
    def load_criteria(path: Path) -> PublishCriteria:
        """Load *PublishCriteria* from a YAML file.

        Uses ``yaml.safe_load`` if yaml is available, otherwise falls back
        to a simple dict-based parse for the minimal subset used here.
        """
        text = path.read_text(encoding="utf-8")
        try:
            import yaml  # type: ignore[import-not-found]

            data = yaml.safe_load(text)
        except ImportError:
            data = _minimal_yaml_parse(text)
        return PublishCriteria.model_validate(data or {})

    def evaluate(self, criteria: PublishCriteria) -> PublishGateResult:
        """Evaluate *self._fixture* against *criteria* for each run mode."""
        per_mode: list[ModeResult] = []

        for run_mode, thresholds in criteria.thresholds.items():
            eval_result = evaluate_fixture(self._fixture, run_mode)
            failures: list[str] = []
            warnings: list[str] = []
            _compare_thresholds(eval_result.metrics, thresholds, failures, warnings)
            passed = not failures
            per_mode.append(
                ModeResult(
                    mode=run_mode,
                    passed=passed,
                    metrics=eval_result.metrics,
                    failures=list(failures),
                    warnings=list(warnings),
                )
            )

        overall_pass = all(m.passed for m in per_mode)
        return PublishGateResult(
            overall_pass=overall_pass,
            per_mode=per_mode,
            evaluated_at=datetime.now(timezone.utc).isoformat(),
            fixture_id=self._fixture.id,
            criteria_version=criteria.version,
        )

    @staticmethod
    def default_criteria(fixture_id: str) -> PublishCriteria:
        """Return the three-tier default threshold configuration."""
        return PublishCriteria(
            fixture_id=fixture_id,
            description="Default three-tier publish thresholds (baseline / schedule_only / ktsl_full).",
            thresholds={
                "baseline": ModeThresholds(
                    max_causal_violations=5,
                    max_retcons=3,
                ),
                "schedule_only": ModeThresholds(
                    max_causal_violations=2,
                    max_unauthorized_actions=4,
                    max_retcons=1,
                ),
                "ktsl_full": ModeThresholds(
                    max_causal_violations=0,
                    max_unauthorized_actions=0,
                    max_public_payload_leaks=0,
                    max_spotlight_gap_minutes=30,
                    min_declassification_completeness=0.95,
                    max_retcons=0,
                    max_high_coupling_drift_minutes=15,
                ),
            },
        )


# ---------------------------------------------------------------------------
# Threshold comparison
# ---------------------------------------------------------------------------


def _compare_thresholds(
    metrics: "MetricSummary",
    thresholds: ModeThresholds,
    failures: list[str],
    warnings: list[str],
) -> None:
    """Append violations to *failures* / *warnings* for any threshold breach."""
    _check_max(
        "causal_violation",
        metrics.causal_violation_count,
        thresholds.max_causal_violations,
        failures,
        warnings,
    )
    _check_max(
        "unauthorized_action",
        metrics.unauthorized_action_count,
        thresholds.max_unauthorized_actions,
        failures,
        warnings,
    )
    _check_max(
        "public_payload_leak",
        metrics.public_payload_leak_count,
        thresholds.max_public_payload_leaks,
        failures,
        warnings,
    )
    _check_max(
        "spotlight_gap",
        metrics.spotlight_max_gap_minutes,
        thresholds.max_spotlight_gap_minutes,
        failures,
        warnings,
    )
    _check_min(
        "declassification_completeness",
        metrics.declassification_completeness,
        thresholds.min_declassification_completeness,
        failures,
        warnings,
    )
    _check_max(
        "retcon",
        metrics.retcon_count,
        thresholds.max_retcons,
        failures,
        warnings,
    )
    _check_max(
        "high_coupling_drift",
        metrics.high_coupling_time_drift_minutes,
        thresholds.max_high_coupling_drift_minutes,
        failures,
        warnings,
    )


def _check_max(
    name: str,
    actual: int,
    limit: int | None,
    failures: list[str],
    warnings: list[str],
) -> None:
    if limit is None:
        warnings.append(f"No threshold set for {name}: skipped (soft gate)")
        return
    if actual > limit:
        failures.append(f"{name}: {actual} > {limit}")


def _check_min(
    name: str,
    actual: float,
    limit: float | None,
    failures: list[str],
    warnings: list[str],
) -> None:
    if limit is None:
        warnings.append(f"No threshold set for {name}: skipped (soft gate)")
        return
    if actual < limit:
        failures.append(f"{name}: {actual} < {limit}")


# ---------------------------------------------------------------------------
# Minimal YAML subset parser (zero-dep fallback)
# ---------------------------------------------------------------------------


def _minimal_yaml_parse(text: str) -> dict[str, Any]:
    """Parse the minimal publish-criteria subset we use.

    Only supports flat keys, lists, dicts, ints, floats, strings.
    """
    result: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, result)]
    current_list_key: str | None = None
    for raw_line in text.splitlines():
        stripped = raw_line.rstrip()
        if not stripped or stripped.lstrip().startswith("#"):
            continue
        indent = len(stripped) - len(stripped.lstrip())
        line = stripped.rstrip()
        # pop stack to find parent
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]

        if line.startswith("- "):
            # list item
            item_str = line[2:].strip()
            if current_list_key and isinstance(parent.get(current_list_key), list):
                parent[current_list_key].append(_parse_scalar(item_str))
            else:
                if not isinstance(parent, list):
                    # we are inside a dict, list items at this indent
                    # this is an inline list under a key
                    pass
        elif ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value:
                parent[key] = _parse_scalar(value)
            else:
                new_dict: dict[str, Any] = {}
                parent[key] = new_dict
                stack.append((indent, new_dict))
                # check next lines to infer if it's a list or dict
                current_list_key = None
        # else: ignore
    return result


def _parse_scalar(value: str) -> Any:
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(v.strip()) for v in inner.split(",")]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value

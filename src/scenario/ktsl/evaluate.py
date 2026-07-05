"""Deterministic local evaluation runner for KTSL research fixtures."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from typing import Any, cast

from .audit import audit_fixture
from .coupling import evaluate_couplings
from .filter import filter_fixture
from .fixtures import KTSL_FIXTURE_IDS, get_ktsl_fixture, list_ktsl_fixtures
from .models import EvaluationResult, KTSLFixture, MetricSummary, RunMode
from .schedule import schedule_events

RUN_MODE_ORDER: tuple[RunMode, ...] = ("baseline", "schedule_only", "ktsl_full")
SIMULATED_DATA_NOTICE = (
    "Results are generated from deterministic simulated fixtures, not real play evidence."
)

METRIC_COLUMNS: tuple[tuple[str, str], ...] = (
    ("causal_violation", "causal_violation_count"),
    ("unauthorized_action", "unauthorized_action_count"),
    ("public_payload_leak", "public_payload_leak_count"),
    ("spotlight_max_gap", "spotlight_max_gap_minutes"),
    ("declassification", "declassification_completeness"),
    ("retcon", "retcon_count"),
    ("high_coupling_time_drift", "high_coupling_time_drift_minutes"),
    ("barrier_wait", "barrier_wait_minutes"),
    ("committed_events", "committed_event_count"),
    ("blocked_events", "blocked_event_count"),
)


def evaluate_fixture(fixture: KTSLFixture, run_mode: RunMode) -> EvaluationResult:
    """Evaluate one deterministic fixture in one run mode."""

    schedule_steps = schedule_events(fixture, run_mode)
    filter_decisions = filter_fixture(fixture, run_mode, schedule_steps)
    coupling_decisions = evaluate_couplings(fixture, run_mode, schedule_steps)
    audit_entries, metrics = audit_fixture(
        fixture=fixture,
        run_mode=run_mode,
        schedule_steps=schedule_steps,
        filter_decisions=filter_decisions,
        coupling_decisions=coupling_decisions,
    )
    return EvaluationResult(
        fixture_id=fixture.id,
        run_mode=run_mode,
        metrics=metrics,
        schedule_steps=schedule_steps,
        filter_decisions=filter_decisions,
        coupling_decisions=coupling_decisions,
        audit_entries=audit_entries,
        simulated_data_notice=SIMULATED_DATA_NOTICE,
        metadata={
            "fixture_title": fixture.title,
            "seed_label": fixture.seed_label,
            "simulation_notice": fixture.simulation_notice,
        },
    )


def evaluate_all(
    fixture_ids: Sequence[str] | None = None,
    run_modes: Sequence[RunMode] | None = None,
) -> list[EvaluationResult]:
    """Evaluate every selected fixture x run mode combination."""

    fixtures = (
        [get_ktsl_fixture(fixture_id) for fixture_id in fixture_ids]
        if fixture_ids is not None
        else list_ktsl_fixtures()
    )
    selected_modes = tuple(run_modes or RUN_MODE_ORDER)
    results: list[EvaluationResult] = []
    for fixture in fixtures:
        for run_mode in selected_modes:
            if run_mode in fixture.run_modes:
                results.append(evaluate_fixture(fixture, run_mode))
    return results


def results_payload(results: Sequence[EvaluationResult]) -> dict[str, Any]:
    """Return a stable JSON-serializable payload for CLI and tests."""

    return {
        "notice": SIMULATED_DATA_NOTICE,
        "results": [result.model_dump(mode="json") for result in results],
    }


def render_results_json(results: Sequence[EvaluationResult]) -> str:
    """Render evaluation results as deterministic JSON."""

    return json.dumps(results_payload(results), ensure_ascii=False, indent=2)


def render_results_markdown(results: Sequence[EvaluationResult]) -> str:
    """Render a compact Markdown metrics table."""

    headers = ["fixture", "mode", *[column[0] for column in METRIC_COLUMNS]]
    lines = [
        "# KTSL Deterministic Evaluation",
        "",
        f"> {SIMULATED_DATA_NOTICE}",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for result in results:
        values = [
            result.fixture_id,
            result.run_mode,
            *[_format_metric(result.metrics, field_name) for _, field_name in METRIC_COLUMNS],
        ]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for ``python -m scenario.ktsl.evaluate``."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format.",
    )
    parser.add_argument(
        "--fixture",
        action="append",
        choices=KTSL_FIXTURE_IDS,
        help="Fixture id to include. May be passed multiple times.",
    )
    parser.add_argument(
        "--mode",
        action="append",
        choices=RUN_MODE_ORDER,
        help="Run mode to include. May be passed multiple times.",
    )
    args = parser.parse_args(argv)
    run_modes = (
        [cast(RunMode, run_mode) for run_mode in args.mode]
        if args.mode is not None
        else None
    )
    results = evaluate_all(fixture_ids=args.fixture, run_modes=run_modes)
    if args.format == "json":
        print(render_results_json(results))
    else:
        print(render_results_markdown(results))
    return 0


def _format_metric(metrics: MetricSummary, field_name: str) -> str:
    value = getattr(metrics, field_name)
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


__all__ = [
    "METRIC_COLUMNS",
    "RUN_MODE_ORDER",
    "SIMULATED_DATA_NOTICE",
    "evaluate_all",
    "evaluate_fixture",
    "main",
    "render_results_json",
    "render_results_markdown",
    "results_payload",
]


if __name__ == "__main__":
    raise SystemExit(main())

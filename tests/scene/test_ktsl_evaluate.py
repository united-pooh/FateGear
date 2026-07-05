from __future__ import annotations

import json
import os
import subprocess
import sys

from scenario.ktsl.evaluate import (
    RUN_MODE_ORDER,
    evaluate_all,
    render_results_markdown,
)
from scenario.ktsl.fixtures import KTSL_FIXTURE_IDS


def test_evaluate_all_returns_every_fixture_mode_pair() -> None:
    results = evaluate_all()

    assert len(results) == len(KTSL_FIXTURE_IDS) * len(RUN_MODE_ORDER)
    assert {
        (result.fixture_id, result.run_mode) for result in results
    } == {
        (fixture_id, run_mode)
        for fixture_id in KTSL_FIXTURE_IDS
        for run_mode in RUN_MODE_ORDER
    }
    assert all(
        "deterministic simulated" in result.simulated_data_notice
        for result in results
    )


def test_markdown_renderer_exposes_stable_metrics_table() -> None:
    markdown = render_results_markdown(evaluate_all())

    assert markdown.startswith("# KTSL Deterministic Evaluation")
    assert "| fixture | mode | causal_violation |" in markdown
    assert "high_coupling_time_drift" in markdown
    assert "library_sewer_church" in markdown
    assert "police_station_hospital_old_house" in markdown


def test_deterministic_oracle_h1_h2_h3_score_remains_two_of_two() -> None:
    results = evaluate_all()
    by_fixture = {
        fixture_id: {
            result.run_mode: result
            for result in results
            if result.fixture_id == fixture_id
        }
        for fixture_id in KTSL_FIXTURE_IDS
    }

    h1_supported = 0
    h2_supported = 0
    h3_supported = 0
    for modes in by_fixture.values():
        baseline = modes["baseline"].metrics
        schedule_only = modes["schedule_only"].metrics
        ktsl_full = modes["ktsl_full"].metrics

        if (
            schedule_only.causal_violation_count
            < baseline.causal_violation_count
            and schedule_only.retcon_count <= baseline.retcon_count
        ):
            h1_supported += 1
        if (
            ktsl_full.unauthorized_action_count
            <= schedule_only.unauthorized_action_count
            and ktsl_full.public_payload_leak_count
            < schedule_only.public_payload_leak_count
            and ktsl_full.declassification_completeness
            > schedule_only.declassification_completeness
        ):
            h2_supported += 1
        if (
            ktsl_full.spotlight_max_gap_minutes
            <= schedule_only.spotlight_max_gap_minutes
            and ktsl_full.high_coupling_time_drift_minutes
            < schedule_only.high_coupling_time_drift_minutes
        ):
            h3_supported += 1

    assert (h1_supported, h2_supported, h3_supported) == (2, 2, 2)


def test_module_cli_json_output_is_parseable() -> None:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = os.pathsep.join(
        path for path in ("src", env.get("PYTHONPATH", "")) if path
    )

    completed = subprocess.run(
        [sys.executable, "-m", "scenario.ktsl.evaluate", "--format", "json"],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["notice"].startswith("Results are generated")
    assert len(payload["results"]) == len(KTSL_FIXTURE_IDS) * len(RUN_MODE_ORDER)
    assert {
        result["run_mode"] for result in payload["results"]
    } == set(RUN_MODE_ORDER)

from __future__ import annotations

import json

from scenario.ktsl.live_evaluate import (
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_LONGCAT_BASE_URL,
    LiveProviderConfig,
    ProviderCallResult,
    build_live_audit_prompt,
    collect_provider_configs,
    load_zshrc_env,
    render_live_results_markdown,
    run_live_evaluation,
)
from scenario.ktsl.fixtures import get_ktsl_fixture


def test_load_zshrc_env_reads_only_whitelisted_exports(tmp_path) -> None:
    zshrc = tmp_path / ".zshrc"
    zshrc.write_text(
        "\n".join(
            [
                'export LONGCAT_API_KEY="ak-test"',
                "export DEEPSEEK_API_KEY='sk-test'",
                'export UNRELATED_SECRET="do-not-read"',
            ]
        ),
        encoding="utf-8",
    )

    values = load_zshrc_env(zshrc)

    assert values == {
        "LONGCAT_API_KEY": "ak-test",
        "DEEPSEEK_API_KEY": "sk-test",
    }


def test_collect_provider_configs_uses_zshrc_without_exposing_keys(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("LONGCAT_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    zshrc = tmp_path / ".zshrc"
    zshrc.write_text(
        "\n".join(
            [
                "export LONGCAT_API_KEY=ak-test",
                "export DEEPSEEK_API_KEY=sk-test",
            ]
        ),
        encoding="utf-8",
    )

    configs = collect_provider_configs(zshrc_path=zshrc)

    assert [config.provider_id for config in configs] == ["longcat", "deepseek"]
    assert configs[0].base_url == DEFAULT_LONGCAT_BASE_URL
    assert configs[1].base_url == DEFAULT_DEEPSEEK_BASE_URL
    assert configs[0].public_dict()["api_key_present"] is True
    assert "api_key" not in configs[0].public_dict()


def test_run_live_evaluation_compares_mock_provider_metrics() -> None:
    provider = LiveProviderConfig(
        provider_id="mock",
        display_name="Mock",
        model="mock-model",
        api_key="test-key",
        base_url="https://example.invalid/v1",
    )

    def provider_call(
        _provider: LiveProviderConfig,
        _system_prompt: str,
        user_prompt: str,
    ) -> ProviderCallResult:
        request = json.loads(user_prompt)
        metrics = _oracle_like_metrics(
            request["fixture"]["id"],
            request["run_mode"],
        )
        return ProviderCallResult(
            raw_text=json.dumps({"metrics": metrics, "evidence": ["ok"]}),
            latency_ms=123,
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        )

    payload = run_live_evaluation([provider], provider_call=provider_call)

    summary = payload["model_summaries"][0]
    assert summary["case_count"] == 6
    assert summary["ok_count"] == 6
    assert summary["json_valid_count"] == 6
    assert summary["metric_match_rate"] == 1.0
    assert summary["hypothesis_direction"]["h1_causal"] == {"passed": 2, "total": 2}
    assert summary["hypothesis_direction"]["h2_filter"] == {"passed": 2, "total": 2}
    assert summary["hypothesis_direction"]["h3_coupling"] == {"passed": 2, "total": 2}
    markdown = render_live_results_markdown(payload)
    assert "# KTSL Live Provider Evaluation" in markdown
    assert "| mock | mock-model | 6 | 6 | 6 | 1.00 | 2/2 | 2/2 | 2/2 |" in markdown


def test_live_prompt_uses_canonical_outputs_not_event_seed_status() -> None:
    _system_prompt, user_prompt = build_live_audit_prompt(
        fixture=get_ktsl_fixture("library_sewer_church"),
        run_mode="baseline",
    )
    payload = json.loads(user_prompt)

    assert "canonical_ktsl_outputs" in payload
    assert any(
        "fixture.events[].status is only a seed/proposal status" in item
        for item in payload["important_semantics"]
    )
    schedule_steps = payload["canonical_ktsl_outputs"]["schedule_steps"]
    church_step = next(
        step
        for step in schedule_steps
        if step["event_id"] == "evt_church_open_reliquary"
    )
    assert church_step["status"] == "committed"
    assert any(
        entry["metric"] == "causal_violation"
        for entry in payload["canonical_ktsl_outputs"]["audit_entries"]
    )


def _oracle_like_metrics(fixture_id: str, run_mode: str) -> dict[str, int | float]:
    if fixture_id == "library_sewer_church":
        leak_baseline, leak_schedule = 1, 1
        unauthorized_baseline, unauthorized_schedule = 0, 0
    else:
        leak_baseline, leak_schedule = 2, 2
        unauthorized_baseline, unauthorized_schedule = 1, 1

    metrics = {
        "causal_violation_count": 0,
        "unauthorized_action_count": 0,
        "public_payload_leak_count": 0,
        "spotlight_max_gap_minutes": 0,
        "declassification_completeness": 1.0,
        "retcon_count": 0,
        "high_coupling_time_drift_minutes": 0,
        "barrier_wait_minutes": 2,
        "committed_event_count": 3,
        "blocked_event_count": 0,
    }
    if run_mode == "baseline":
        metrics.update(
            {
                "causal_violation_count": 1,
                "unauthorized_action_count": unauthorized_baseline,
                "public_payload_leak_count": leak_baseline,
                "declassification_completeness": 0.0,
                "high_coupling_time_drift_minutes": 5,
                "barrier_wait_minutes": 0,
            }
        )
    elif run_mode == "schedule_only":
        metrics.update(
            {
                "unauthorized_action_count": unauthorized_schedule,
                "public_payload_leak_count": leak_schedule,
                "declassification_completeness": 0.0,
                "high_coupling_time_drift_minutes": 3,
            }
        )
    return metrics

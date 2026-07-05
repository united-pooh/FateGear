"""Live provider evaluation for KTSL fixtures.

This module keeps live LLM calls separate from the deterministic KTSL oracle in
``evaluate.py``. Provider responses are treated as model audit attempts and are
compared with the deterministic fixture metrics.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, cast

from .evaluate import METRIC_COLUMNS, RUN_MODE_ORDER, evaluate_all, evaluate_fixture
from .fixtures import KTSL_FIXTURE_IDS, get_ktsl_fixture
from .models import EvaluationResult, KTSLFixture, MetricSummary, RunMode

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-pro"
DEFAULT_LONGCAT_BASE_URL = "https://api.longcat.chat/openai/v1"
DEFAULT_LONGCAT_MODEL = "LongCat-2.0"
LIVE_NOTICE = (
    "Live provider results call external APIs and compare model-produced audit "
    "metrics with the deterministic KTSL oracle."
)
ZSHRC_ENV_KEYS = {
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_MODEL",
    "KTSL_DEEPSEEK_BASE_URL",
    "KTSL_DEEPSEEK_MODEL",
    "LONGCAT_API_KEY",
    "LONGCAT_BASE_URL",
    "LONGCAT_MODEL",
    "KTSL_LONGCAT_BASE_URL",
    "KTSL_LONGCAT_MODEL",
}
METRIC_FIELD_NAMES = tuple(field_name for _, field_name in METRIC_COLUMNS)


@dataclass(frozen=True)
class LiveProviderConfig:
    """Configuration for one OpenAI-compatible live provider."""

    provider_id: str
    display_name: str
    model: str
    api_key: str
    base_url: str
    timeout_seconds: float = 60.0
    max_tokens: int = 1600
    json_mode: bool = True

    def public_dict(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "model": self.model,
            "base_url": self.base_url,
            "timeout_seconds": self.timeout_seconds,
            "max_tokens": self.max_tokens,
            "json_mode": self.json_mode,
            "api_key_present": bool(self.api_key),
        }


@dataclass
class ProviderCallResult:
    """Raw outcome of one provider call."""

    raw_text: str = ""
    latency_ms: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    error: str = ""
    retried_without_json_mode: bool = False


@dataclass
class LiveCaseResult:
    """One fixture/mode audit attempt by one provider."""

    provider_id: str
    model: str
    fixture_id: str
    run_mode: RunMode
    status: str
    latency_ms: int
    oracle_metrics: dict[str, int | float]
    model_metrics: dict[str, int | float | None] = field(default_factory=dict)
    metric_exact_matches: int = 0
    metric_total: int = len(METRIC_FIELD_NAMES)
    json_valid: bool = False
    error: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    retried_without_json_mode: bool = False
    retried_invalid_json: bool = False
    evidence: list[str] = field(default_factory=list)
    raw_response: str = ""


ProviderCall = Callable[[LiveProviderConfig, str, str], ProviderCallResult]


def load_zshrc_env(path: str | Path | None = None) -> dict[str, str]:
    """Read whitelisted provider variables from a zshrc-style export file.

    The parser intentionally supports only simple ``export KEY=value`` lines and
    never executes shell code.
    """

    resolved = Path(path).expanduser() if path is not None else Path.home() / ".zshrc"
    if not resolved.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in resolved.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key not in ZSHRC_ENV_KEYS:
            continue
        try:
            parts = shlex.split(raw_value, comments=False, posix=True)
        except ValueError:
            continue
        if parts:
            values[key] = parts[0]
    return values


def collect_provider_configs(
    *,
    provider_ids: Sequence[str] | None = None,
    timeout_seconds: float = 60.0,
    max_tokens: int = 1600,
    json_mode: bool = True,
    load_zshrc: bool = True,
    zshrc_path: str | Path | None = None,
) -> list[LiveProviderConfig]:
    """Collect provider configs from process env plus whitelisted zshrc values."""

    zshrc_values = load_zshrc_env(zshrc_path) if load_zshrc else {}
    requested = set(provider_ids or ("longcat", "deepseek"))
    configs: list[LiveProviderConfig] = []
    if "longcat" in requested:
        longcat_key = _read_config("LONGCAT_API_KEY", zshrc_values)
        if longcat_key:
            configs.append(
                LiveProviderConfig(
                    provider_id="longcat",
                    display_name="LongCat",
                    model=_read_config(
                        "KTSL_LONGCAT_MODEL",
                        zshrc_values,
                        aliases=("LONGCAT_MODEL",),
                        default=DEFAULT_LONGCAT_MODEL,
                    ),
                    api_key=longcat_key,
                    base_url=_read_config(
                        "KTSL_LONGCAT_BASE_URL",
                        zshrc_values,
                        aliases=("LONGCAT_BASE_URL",),
                        default=DEFAULT_LONGCAT_BASE_URL,
                    ),
                    timeout_seconds=timeout_seconds,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
            )
    if "deepseek" in requested:
        deepseek_key = _read_config("DEEPSEEK_API_KEY", zshrc_values)
        if deepseek_key:
            configs.append(
                LiveProviderConfig(
                    provider_id="deepseek",
                    display_name="DeepSeek",
                    model=_read_config(
                        "KTSL_DEEPSEEK_MODEL",
                        zshrc_values,
                        aliases=("DEEPSEEK_MODEL",),
                        default=DEFAULT_DEEPSEEK_MODEL,
                    ),
                    api_key=deepseek_key,
                    base_url=_read_config(
                        "KTSL_DEEPSEEK_BASE_URL",
                        zshrc_values,
                        aliases=("DEEPSEEK_BASE_URL",),
                        default=DEFAULT_DEEPSEEK_BASE_URL,
                    ),
                    timeout_seconds=timeout_seconds,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                )
            )
    return configs


def run_live_evaluation(
    providers: Sequence[LiveProviderConfig],
    *,
    fixture_ids: Sequence[str] | None = None,
    run_modes: Sequence[RunMode] | None = None,
    provider_call: ProviderCall | None = None,
    retry_invalid_json: bool = True,
) -> dict[str, Any]:
    """Run live provider audits and return comparison statistics."""

    selected_modes = tuple(run_modes or RUN_MODE_ORDER)
    selected_fixture_ids = tuple(fixture_ids or KTSL_FIXTURE_IDS)
    oracle_results = evaluate_all(selected_fixture_ids, selected_modes)
    oracle_lookup = {
        (result.fixture_id, result.run_mode): result for result in oracle_results
    }
    caller = provider_call or call_openai_compatible

    case_results: list[LiveCaseResult] = []
    for provider in providers:
        for fixture_id in selected_fixture_ids:
            fixture = get_ktsl_fixture(fixture_id)
            for run_mode in selected_modes:
                oracle = oracle_lookup[(fixture_id, run_mode)]
                system_prompt, user_prompt = build_live_audit_prompt(
                    fixture=fixture,
                    run_mode=run_mode,
                )
                call_result = caller(provider, system_prompt, user_prompt)
                case = compare_provider_output(
                    provider=provider,
                    fixture_id=fixture_id,
                    run_mode=run_mode,
                    oracle=oracle,
                    call_result=call_result,
                )
                if retry_invalid_json and case.status == "invalid_json":
                    retry_provider = replace(
                        provider,
                        max_tokens=max(provider.max_tokens * 2, provider.max_tokens + 400),
                    )
                    retry_result = caller(retry_provider, system_prompt, user_prompt)
                    retry_case = compare_provider_output(
                        provider=retry_provider,
                        fixture_id=fixture_id,
                        run_mode=run_mode,
                        oracle=oracle,
                        call_result=retry_result,
                    )
                    retry_case.retried_invalid_json = True
                    case = retry_case
                case_results.append(case)

    return live_results_payload(providers, oracle_results, case_results)


def call_openai_compatible(
    provider: LiveProviderConfig,
    system_prompt: str,
    user_prompt: str,
) -> ProviderCallResult:
    """Call one OpenAI-compatible provider synchronously."""

    try:
        from openai import OpenAI
    except ImportError as exc:
        return ProviderCallResult(error=f"openai SDK unavailable: {exc}")

    client = OpenAI(
        api_key=provider.api_key,
        base_url=provider.base_url,
        timeout=provider.timeout_seconds,
    )
    request: dict[str, object] = {
        "model": provider.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0,
        "max_tokens": provider.max_tokens,
    }
    if provider.json_mode:
        request["response_format"] = {"type": "json_object"}
    if provider.provider_id == "deepseek":
        request["extra_body"] = {"thinking": {"type": "disabled"}}

    started = time.perf_counter()
    create_completion = cast(Any, client.chat.completions.create)
    try:
        response = create_completion(**request)
        retried_without_json_mode = False
    except Exception as exc:  # pragma: no cover - exercised only by live APIs
        if not provider.json_mode:
            return ProviderCallResult(
                latency_ms=_elapsed_ms(started),
                error=_sanitize_error(exc),
            )
        request.pop("response_format", None)
        try:
            response = create_completion(**request)
            retried_without_json_mode = True
        except Exception as retry_exc:
            return ProviderCallResult(
                latency_ms=_elapsed_ms(started),
                error=_sanitize_error(retry_exc),
                retried_without_json_mode=True,
            )

    raw_text = ""
    if response.choices:
        message = response.choices[0].message
        raw_text = message.content or str(getattr(message, "reasoning_content", "") or "")
    usage = getattr(response, "usage", None)
    return ProviderCallResult(
        raw_text=raw_text,
        latency_ms=_elapsed_ms(started),
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        total_tokens=getattr(usage, "total_tokens", None),
        retried_without_json_mode=retried_without_json_mode,
    )


def build_live_audit_prompt(
    *,
    fixture: KTSLFixture,
    run_mode: RunMode,
) -> tuple[str, str]:
    """Build a compact KTSL audit prompt for one fixture/mode."""

    system_prompt = (
        "You are auditing a tabletop mystery synchronization protocol named KTSL. "
        "Return one JSON object only. Do not use Markdown. Compute the requested "
        "metrics only from canonical_ktsl_outputs. Do not reconstruct schedule "
        "or filter state from raw fixture fields."
    )
    payload = {
        "task": "Return KTSL audit metrics for this fixture and mode.",
        "important_semantics": [
            "canonical_ktsl_outputs are authoritative.",
            "fixture.events[].status is only a seed/proposal status; it is not the committed result.",
            "Use schedule_steps[].status to count committed and blocked events.",
            "Use audit_entries[].metric to count causal_violation, unauthorized_action, public_payload_leak, and retcon.",
            "Use coupling_decisions[].drift_minutes to sum high_coupling_time_drift_minutes for high-coupling decisions.",
            "Use declassification_expected_pairs and filter_decisions[].declassified to compute declassification_completeness.",
        ],
        "response_schema": {
            "metrics": {
                field_name: "number"
                for field_name in METRIC_FIELD_NAMES
            },
            "evidence": ["short reason strings"],
        },
        "run_mode": run_mode,
        "run_mode_rules": _run_mode_rules(run_mode),
        "metric_counting_rules": _metric_counting_rules(),
        "canonical_ktsl_outputs": _canonical_outputs(fixture, run_mode),
        "fixture": _compact_fixture(fixture),
    }
    return system_prompt, json.dumps(payload, ensure_ascii=False, indent=2)


def compare_provider_output(
    *,
    provider: LiveProviderConfig,
    fixture_id: str,
    run_mode: RunMode,
    oracle: EvaluationResult,
    call_result: ProviderCallResult,
) -> LiveCaseResult:
    """Compare one provider response with deterministic oracle metrics."""

    oracle_metrics = _metrics_dict(oracle.metrics)
    if call_result.error:
        return LiveCaseResult(
            provider_id=provider.provider_id,
            model=provider.model,
            fixture_id=fixture_id,
            run_mode=run_mode,
            status="error",
            latency_ms=call_result.latency_ms,
            oracle_metrics=oracle_metrics,
            error=call_result.error,
            prompt_tokens=call_result.prompt_tokens,
            completion_tokens=call_result.completion_tokens,
            total_tokens=call_result.total_tokens,
            retried_without_json_mode=call_result.retried_without_json_mode,
        )

    parsed = _load_json_object(call_result.raw_text)
    if not isinstance(parsed, dict):
        return LiveCaseResult(
            provider_id=provider.provider_id,
            model=provider.model,
            fixture_id=fixture_id,
            run_mode=run_mode,
            status="invalid_json",
            latency_ms=call_result.latency_ms,
            oracle_metrics=oracle_metrics,
            json_valid=False,
            error="response did not contain a JSON object",
            prompt_tokens=call_result.prompt_tokens,
            completion_tokens=call_result.completion_tokens,
            total_tokens=call_result.total_tokens,
            retried_without_json_mode=call_result.retried_without_json_mode,
            raw_response=call_result.raw_text,
        )

    model_metrics = _coerce_metric_values(parsed.get("metrics", parsed))
    metric_exact_matches = sum(
        1
        for field_name, oracle_value in oracle_metrics.items()
        if _metric_equal(model_metrics.get(field_name), oracle_value)
    )
    return LiveCaseResult(
        provider_id=provider.provider_id,
        model=provider.model,
        fixture_id=fixture_id,
        run_mode=run_mode,
        status="ok",
        latency_ms=call_result.latency_ms,
        oracle_metrics=oracle_metrics,
        model_metrics=model_metrics,
        metric_exact_matches=metric_exact_matches,
        json_valid=True,
        prompt_tokens=call_result.prompt_tokens,
        completion_tokens=call_result.completion_tokens,
        total_tokens=call_result.total_tokens,
        retried_without_json_mode=call_result.retried_without_json_mode,
        evidence=[
            str(item)[:240]
            for item in parsed.get("evidence", [])
            if isinstance(item, str)
        ][:5],
        raw_response=call_result.raw_text,
    )


def live_results_payload(
    providers: Sequence[LiveProviderConfig],
    oracle_results: Sequence[EvaluationResult],
    case_results: Sequence[LiveCaseResult],
) -> dict[str, Any]:
    """Build a stable serializable payload for live provider results."""

    providers_public = [provider.public_dict() for provider in providers]
    cases = [asdict(result) for result in case_results]
    return {
        "notice": LIVE_NOTICE,
        "providers": providers_public,
        "oracle_results": [
            {
                "fixture_id": result.fixture_id,
                "run_mode": result.run_mode,
                "metrics": _metrics_dict(result.metrics),
            }
            for result in oracle_results
        ],
        "cases": cases,
        "model_summaries": [
            _summarize_provider(provider, case_results)
            for provider in providers
        ],
    }


def render_live_results_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_live_results_markdown(payload: dict[str, Any]) -> str:
    """Render live provider statistics as Markdown."""

    lines = [
        "# KTSL Live Provider Evaluation",
        "",
        f"> {payload['notice']}",
        "",
        "## Model Summary",
        "",
        "| provider | model | cases | ok | json_valid | metric_match_rate | H1 | H2 | H3 | avg_latency_ms | total_tokens |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for summary in payload["model_summaries"]:
        directions = summary["hypothesis_direction"]
        lines.append(
            "| {provider_id} | {model} | {case_count} | {ok_count} | {json_valid_count} | "
            "{metric_match_rate:.2f} | {h1} | {h2} | {h3} | {avg_latency_ms} | {total_tokens} |".format(
                provider_id=summary["provider_id"],
                model=summary["model"],
                case_count=summary["case_count"],
                ok_count=summary["ok_count"],
                json_valid_count=summary["json_valid_count"],
                metric_match_rate=summary["metric_match_rate"],
                h1=_ratio_label(directions["h1_causal"]),
                h2=_ratio_label(directions["h2_filter"]),
                h3=_ratio_label(directions["h3_coupling"]),
                avg_latency_ms=summary["avg_latency_ms"],
                total_tokens=summary["total_tokens"],
            )
        )
    lines.extend(
        [
            "",
            "## Case Metrics",
            "",
            "| provider | fixture | mode | status | exact | oracle causal/leak/declass/drift | model causal/leak/declass/drift | latency_ms |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for case in payload["cases"]:
        oracle = case["oracle_metrics"]
        model = case.get("model_metrics", {})
        lines.append(
            "| {provider_id} | {fixture_id} | {run_mode} | {status} | {exact}/{total} | "
            "{oracle_vals} | {model_vals} | {latency_ms} |".format(
                provider_id=case["provider_id"],
                fixture_id=case["fixture_id"],
                run_mode=case["run_mode"],
                status=case["status"],
                exact=case["metric_exact_matches"],
                total=case["metric_total"],
                oracle_vals=_short_metrics(oracle),
                model_vals=_short_metrics(model),
                latency_ms=case["latency_ms"],
            )
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument(
        "--provider",
        action="append",
        choices=("longcat", "deepseek"),
        help="Provider to include. Defaults to both.",
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
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-tokens", type=int, default=1600)
    parser.add_argument("--no-zshrc", action="store_true")
    parser.add_argument("--no-json-mode", action="store_true")
    args = parser.parse_args(argv)

    providers = collect_provider_configs(
        provider_ids=args.provider,
        timeout_seconds=args.timeout,
        max_tokens=args.max_tokens,
        json_mode=not args.no_json_mode,
        load_zshrc=not args.no_zshrc,
    )
    if not providers:
        requested = ", ".join(args.provider or ["longcat", "deepseek"])
        raise SystemExit(
            f"No provider API keys found for: {requested}. "
            "Set provider keys in environment or ~/.zshrc."
        )
    run_modes = (
        [cast(RunMode, run_mode) for run_mode in args.mode]
        if args.mode is not None
        else None
    )
    payload = run_live_evaluation(
        providers,
        fixture_ids=args.fixture,
        run_modes=run_modes,
    )
    if args.format == "json":
        print(render_live_results_json(payload))
    else:
        print(render_live_results_markdown(payload))
    return 0


def _read_config(
    key: str,
    zshrc_values: dict[str, str],
    *,
    aliases: tuple[str, ...] = (),
    default: str = "",
) -> str:
    for candidate in (key, *aliases):
        value = os.environ.get(candidate)
        if value:
            return value
    for candidate in (key, *aliases):
        value = zshrc_values.get(candidate)
        if value:
            return value
    return default


def _run_mode_rules(run_mode: RunMode) -> dict[str, str]:
    common = {
        "causal_violation_count": "Count committed settleable events that violate happened-before dependencies.",
        "public_payload_leak_count": "Count unauthorized sensitive public payload exposures.",
        "high_coupling_time_drift_minutes": "Sum drift minutes for high-coupling scene links.",
    }
    if run_mode == "baseline":
        return {
            **common,
            "mode": "Commit by spotlight order; do not enforce Schedule barriers, Filter redaction, or Coupling synchronization.",
        }
    if run_mode == "schedule_only":
        return {
            **common,
            "mode": "Enforce Schedule barriers and happened-before ordering, but keep baseline public payload behavior and no full coupling synchronization.",
        }
    return {
        **common,
        "mode": "Apply Schedule barriers, Filter redaction/declassification, and Coupling synchronization.",
    }


def _metric_counting_rules() -> dict[str, str]:
    return {
        "causal_violation_count": "Count distinct audit_entries with metric == 'causal_violation'.",
        "unauthorized_action_count": "Count distinct audit_entries with metric == 'unauthorized_action'.",
        "public_payload_leak_count": "Count distinct audit_entries with metric == 'public_payload_leak'.",
        "spotlight_max_gap_minutes": "Sort committed schedule_steps by spotlight_start_minute; take max gap between current.spotlight_start_minute and previous.spotlight_end_minute, floored at 0.",
        "declassification_completeness": "Count expected pairs whose info_id/character_id pair has a matching filter_decision with declassified == true or status == 'declassified', divided by total expected pairs.",
        "retcon_count": "Count distinct audit_entries with metric == 'retcon'.",
        "high_coupling_time_drift_minutes": "Sum drift_minutes for coupling_decisions where coupling_score >= 0.75.",
        "barrier_wait_minutes": "Sum schedule_steps[].wait_cost_minutes.",
        "committed_event_count": "Count schedule_steps with status == 'committed'.",
        "blocked_event_count": "Count schedule_steps with status == 'blocked'.",
    }


def _canonical_outputs(fixture: KTSLFixture, run_mode: RunMode) -> dict[str, object]:
    result = evaluate_fixture(fixture, run_mode)
    return {
        "schedule_steps": [
            {
                "event_id": step.event_id,
                "scene_id": step.scene_id,
                "status": step.status,
                "commit_index": step.commit_index,
                "wait_cost_minutes": step.wait_cost_minutes,
                "depends_on_event_ids": step.depends_on_event_ids,
                "required_info_ids": step.required_info_ids,
                "output_info_ids": step.output_info_ids,
                "missing_event_ids": step.missing_event_ids,
                "missing_info_ids": step.missing_info_ids,
                "time_start_minute": step.time_start_minute,
                "time_end_minute": step.time_end_minute,
                "spotlight_start_minute": step.spotlight_start_minute,
                "spotlight_end_minute": step.spotlight_end_minute,
            }
            for step in result.schedule_steps
        ],
        "filter_decisions": [
            {
                "event_id": decision.event_id,
                "info_id": decision.info_id,
                "character_id": decision.character_id,
                "status": decision.status,
                "authorized": decision.authorized,
                "declassified": decision.declassified,
                "leaked_public_payload": decision.leaked_public_payload,
                "reason_code": decision.reason_code,
            }
            for decision in result.filter_decisions
        ],
        "coupling_decisions": [
            {
                "coupling_id": decision.coupling_id,
                "status": decision.status,
                "coupling_score": decision.coupling_score,
                "barrier_required": decision.barrier_required,
                "unmet_required_info_ids": decision.unmet_required_info_ids,
                "unmet_required_scene_ids": decision.unmet_required_scene_ids,
                "unmet_input_event_ids": decision.unmet_input_event_ids,
                "drift_minutes": decision.drift_minutes,
            }
            for decision in result.coupling_decisions
        ],
        "audit_entries": [
            {
                "metric": entry.metric,
                "event_id": entry.event_id,
                "info_id": entry.info_id,
                "severity": entry.severity,
                "caused_by_event_ids": entry.caused_by_event_ids,
                "caused_by_info_ids": entry.caused_by_info_ids,
                "message": entry.message,
            }
            for entry in result.audit_entries
        ],
        "declassification_expected_pairs": [
            {
                "info_id": info.id,
                "character_id": character_id,
            }
            for info in fixture.info_labels
            if info.should_declassify or info.id in fixture.expected_declassified_info_ids
            for character_id in info.expected_declassified_for_character_ids
        ],
    }


def _compact_fixture(fixture: KTSLFixture) -> dict[str, object]:
    return {
        "id": fixture.id,
        "title": fixture.title,
        "events": [
            {
                "id": event.id,
                "scene_id": event.scene_id,
                "actor": event.actor,
                "character_id": event.character_id,
                "status": event.status,
                "depends_on_event_ids": event.depends_on_event_ids,
                "causal_dependency_ids": event.causal_dependency_ids,
                "required_info_ids": event.required_info_ids,
                "observed_info_ids": event.observed_info_ids,
                "known_info_ids": event.known_info_ids,
                "output_info_ids": event.output_info_ids,
                "time": [event.time_start_minute, event.time_end_minute],
                "spotlight": [event.spotlight_start_minute, event.spotlight_end_minute],
                "public_payload": event.public_payload,
                "redaction": event.redaction,
            }
            for event in fixture.events
        ],
        "causal_dependencies": [
            dependency.model_dump(mode="json")
            for dependency in fixture.causal_dependencies
        ],
        "barriers": [barrier.model_dump(mode="json") for barrier in fixture.barriers],
        "info_labels": [
            {
                "id": info.id,
                "kind": info.kind,
                "sensitivity": info.sensitivity,
                "authorized_character_ids": info.authorized_character_ids,
                "expected_declassified_for_character_ids": info.expected_declassified_for_character_ids,
                "should_declassify": info.should_declassify,
                "public_payload": info.public_payload,
                "redaction": info.redaction,
            }
            for info in fixture.info_labels
        ],
        "initial_knowledge": [
            state.model_dump(mode="json") for state in fixture.initial_knowledge
        ],
        "couplings": [
            coupling.model_dump(mode="json") for coupling in fixture.couplings
        ],
    }


def _metrics_dict(metrics: MetricSummary) -> dict[str, int | float]:
    return {
        field_name: getattr(metrics, field_name)
        for field_name in METRIC_FIELD_NAMES
    }


def _coerce_metric_values(value: object) -> dict[str, int | float | None]:
    if not isinstance(value, dict):
        return {field_name: None for field_name in METRIC_FIELD_NAMES}
    metrics: dict[str, int | float | None] = {}
    for field_name in METRIC_FIELD_NAMES:
        raw = value.get(field_name)
        metrics[field_name] = _coerce_number(raw)
    return metrics


def _coerce_number(value: object) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            number = float(normalized)
        except ValueError:
            return None
        return int(number) if number.is_integer() else number
    return None


def _metric_equal(model_value: int | float | None, oracle_value: int | float) -> bool:
    if model_value is None:
        return False
    return abs(float(model_value) - float(oracle_value)) < 0.005


def _load_json_object(raw_text: str) -> object:
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _summarize_provider(
    provider: LiveProviderConfig,
    case_results: Sequence[LiveCaseResult],
) -> dict[str, Any]:
    cases = [case for case in case_results if case.provider_id == provider.provider_id]
    ok_cases = [case for case in cases if case.status == "ok"]
    metric_total = sum(case.metric_total for case in ok_cases)
    metric_matches = sum(case.metric_exact_matches for case in ok_cases)
    latencies = [case.latency_ms for case in cases if case.latency_ms > 0]
    total_tokens = sum(case.total_tokens or 0 for case in cases)
    return {
        "provider_id": provider.provider_id,
        "model": provider.model,
        "case_count": len(cases),
        "ok_count": len(ok_cases),
        "error_count": len([case for case in cases if case.status == "error"]),
        "json_valid_count": len([case for case in cases if case.json_valid]),
        "metric_exact_matches": metric_matches,
        "metric_total": metric_total,
        "metric_match_rate": metric_matches / metric_total if metric_total else 0.0,
        "avg_latency_ms": round(sum(latencies) / len(latencies)) if latencies else 0,
        "prompt_tokens": sum(case.prompt_tokens or 0 for case in cases),
        "completion_tokens": sum(case.completion_tokens or 0 for case in cases),
        "total_tokens": total_tokens,
        "hypothesis_direction": _hypothesis_direction(cases),
    }


def _hypothesis_direction(cases: Sequence[LiveCaseResult]) -> dict[str, dict[str, int]]:
    by_fixture_mode = {
        (case.fixture_id, case.run_mode): case.model_metrics
        for case in cases
        if case.status == "ok"
    }
    fixture_ids = sorted({case.fixture_id for case in cases})
    totals = {"h1_causal": 0, "h2_filter": 0, "h3_coupling": 0}
    passed = {"h1_causal": 0, "h2_filter": 0, "h3_coupling": 0}
    for fixture_id in fixture_ids:
        baseline = by_fixture_mode.get((fixture_id, "baseline"))
        schedule = by_fixture_mode.get((fixture_id, "schedule_only"))
        full = by_fixture_mode.get((fixture_id, "ktsl_full"))
        if baseline and schedule:
            totals["h1_causal"] += 1
            if _value(baseline, "causal_violation_count") > _value(
                schedule, "causal_violation_count"
            ):
                passed["h1_causal"] += 1
        if schedule and full:
            totals["h2_filter"] += 1
            schedule_leaks = _value(schedule, "unauthorized_action_count") + _value(
                schedule, "public_payload_leak_count"
            )
            full_leaks = _value(full, "unauthorized_action_count") + _value(
                full, "public_payload_leak_count"
            )
            if schedule_leaks > full_leaks and _value(
                full, "declassification_completeness"
            ) > _value(schedule, "declassification_completeness"):
                passed["h2_filter"] += 1
            totals["h3_coupling"] += 1
            if _value(schedule, "high_coupling_time_drift_minutes") > _value(
                full, "high_coupling_time_drift_minutes"
            ) and _value(full, "spotlight_max_gap_minutes") <= _value(
                schedule, "spotlight_max_gap_minutes"
            ):
                passed["h3_coupling"] += 1
    return {
        key: {"passed": passed[key], "total": totals[key]}
        for key in ("h1_causal", "h2_filter", "h3_coupling")
    }


def _value(metrics: dict[str, int | float | None], field_name: str) -> float:
    value = metrics.get(field_name)
    return float(value) if isinstance(value, int | float) else -1.0


def _short_metrics(metrics: dict[str, object]) -> str:
    values = [
        metrics.get("causal_violation_count", "-"),
        metrics.get("public_payload_leak_count", "-"),
        metrics.get("declassification_completeness", "-"),
        metrics.get("high_coupling_time_drift_minutes", "-"),
    ]
    return "/".join(str(value) for value in values)


def _ratio_label(value: dict[str, int]) -> str:
    return f"{value['passed']}/{value['total']}"


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def _sanitize_error(exc: BaseException) -> str:
    text = str(exc)
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", text)
    text = re.sub(r"ak[_-][A-Za-z0-9_-]+", "ak-***", text)
    return text[:500]


__all__ = [
    "DEFAULT_DEEPSEEK_BASE_URL",
    "DEFAULT_DEEPSEEK_MODEL",
    "DEFAULT_LONGCAT_BASE_URL",
    "DEFAULT_LONGCAT_MODEL",
    "LIVE_NOTICE",
    "LiveCaseResult",
    "LiveProviderConfig",
    "ProviderCallResult",
    "build_live_audit_prompt",
    "call_openai_compatible",
    "collect_provider_configs",
    "compare_provider_output",
    "live_results_payload",
    "load_zshrc_env",
    "main",
    "render_live_results_json",
    "render_live_results_markdown",
    "run_live_evaluation",
]


if __name__ == "__main__":
    raise SystemExit(main())

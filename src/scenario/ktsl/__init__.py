"""Public boundary for the optional KTSL scenario module."""

from __future__ import annotations

from importlib import import_module

from .fixtures import (
    KTSL_FIXTURE_IDS,
    build_library_sewer_church_fixture,
    build_police_hospital_old_house_fixture,
    get_ktsl_fixture,
    list_ktsl_fixtures,
)
from .models import (
    ActorKnowledgeState,
    ActionParseResult,
    AuditEntry,
    AuditMetric,
    AuditResult,
    BarrierCheckpoint,
    BarrierState,
    BarrierStatus,
    CausalDependency,
    ClueRecord,
    CommitRecord,
    CommitStatus,
    ConditionType,
    CouplingDecision,
    CouplingMode,
    CouplingState,
    DecisionStatus,
    EvaluationResult,
    EventRecord,
    FilterDecision,
    InfoKind,
    InfoLabel,
    KTSLFixture,
    KTSLLocation,
    KeeperTruth,
    KnowledgeItem,
    ManualOverrides,
    MetricSummary,
    ModeResult,
    ModeThresholds,
    PublishCriteria,
    PublishGateResult,
    RunMode,
    SceneCard,
    SceneCoupling,
    ScheduleStep,
    SensitivityLevel,
    SessionConfig,
    SessionSummary,
    Visibility,
)

_EVALUATE_EXPORTS = {
    "METRIC_COLUMNS",
    "RUN_MODE_ORDER",
    "SIMULATED_DATA_NOTICE",
    "evaluate_all",
    "evaluate_fixture",
    "render_results_json",
    "render_results_markdown",
    "results_payload",
}
_WIZARD_EXPORTS = {"WizardSession", "build_spec_from_fixture"}
_LOG_WRITER_EXPORTS = {"KTSLLogWriter"}
_LIVE_EVALUATE_EXPORTS = {
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
    "render_live_results_json",
    "render_live_results_markdown",
    "run_live_evaluation",
}


def __getattr__(name: str) -> object:
    if name in _EVALUATE_EXPORTS:
        module = import_module(".evaluate", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name in _LIVE_EVALUATE_EXPORTS:
        module = import_module(".live_evaluate", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name in _WIZARD_EXPORTS:
        module = import_module(".wizard", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name in _LOG_WRITER_EXPORTS:
        module = import_module(".log_writer", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ActorKnowledgeState",
    "ActionParseResult",
    "AuditEntry",
    "AuditMetric",
    "AuditResult",
    "BarrierCheckpoint",
    "BarrierState",
    "BarrierStatus",
    "CausalDependency",
    "ClueRecord",
    "CommitRecord",
    "CommitStatus",
    "ConditionType",
    "CouplingDecision",
    "CouplingMode",
    "CouplingState",
    "DecisionStatus",
    "EvaluationResult",
    "EventRecord",
    "FilterDecision",
    "InfoKind",
    "InfoLabel",
    "KTSLFixture",
    "KTSLLocation",
    "KTSL_FIXTURE_IDS",
    "KeeperTruth",
    "KnowledgeItem",
    "ManualOverrides",
    "MetricSummary",
    "ModeResult",
    "ModeThresholds",
    "PublishCriteria",
    "PublishGateResult",
    "RunMode",
    "SceneCard",
    "SceneCoupling",
    "ScheduleStep",
    "SensitivityLevel",
    "SessionConfig",
    "SessionSummary",
    "Visibility",
    "WizardSession",
    "KTSLLogWriter",
    "DEFAULT_DEEPSEEK_BASE_URL",
    "DEFAULT_DEEPSEEK_MODEL",
    "DEFAULT_LONGCAT_BASE_URL",
    "DEFAULT_LONGCAT_MODEL",
    "LIVE_NOTICE",
    "LiveCaseResult",
    "LiveProviderConfig",
    "METRIC_COLUMNS",
    "MetricSummary",
    "ProviderCallResult",
    "RUN_MODE_ORDER",
    "RunMode",
    "SIMULATED_DATA_NOTICE",
    "SceneCard",
    "SceneCoupling",
    "ScheduleStep",
    "SensitivityLevel",
    "Visibility",
    "build_spec_from_fixture",
    "build_library_sewer_church_fixture",
    "build_police_hospital_old_house_fixture",
    "build_live_audit_prompt",
    "call_openai_compatible",
    "collect_provider_configs",
    "compare_provider_output",
    "evaluate_all",
    "evaluate_fixture",
    "get_ktsl_fixture",
    "live_results_payload",
    "list_ktsl_fixtures",
    "load_zshrc_env",
    "render_results_json",
    "render_live_results_json",
    "render_live_results_markdown",
    "render_results_markdown",
    "results_payload",
    "run_live_evaluation",
]

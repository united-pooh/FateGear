"""Coupling layer for KTSL scene dependency decisions."""

from __future__ import annotations

from .models import CouplingDecision, KTSLFixture, RunMode, SceneCoupling, ScheduleStep

HIGH_COUPLING_THRESHOLD = 0.75


def evaluate_couplings(
    fixture: KTSLFixture,
    run_mode: RunMode,
    schedule_steps: list[ScheduleStep],
) -> list[CouplingDecision]:
    """Evaluate all fixture scene couplings against committed schedule steps."""

    committed_steps = [step for step in schedule_steps if step.status == "committed"]
    committed_event_ids = {step.event_id for step in committed_steps}
    committed_scene_ids = {step.scene_id for step in committed_steps}
    committed_info_ids: set[str] = set()
    for step in committed_steps:
        committed_info_ids.update(step.output_info_ids)

    return [
        evaluate_coupling(
            coupling=coupling,
            run_mode=run_mode,
            schedule_steps=schedule_steps,
            committed_event_ids=committed_event_ids,
            committed_scene_ids=committed_scene_ids,
            committed_info_ids=committed_info_ids,
        )
        for coupling in fixture.couplings
    ]


def evaluate_coupling(
    *,
    coupling: SceneCoupling,
    run_mode: RunMode,
    schedule_steps: list[ScheduleStep],
    committed_event_ids: set[str] | None = None,
    committed_scene_ids: set[str] | None = None,
    committed_info_ids: set[str] | None = None,
) -> CouplingDecision:
    """Evaluate a single coupling with deterministic high/low behavior."""

    committed_event_ids = committed_event_ids or {
        step.event_id for step in schedule_steps if step.status == "committed"
    }
    committed_scene_ids = committed_scene_ids or {
        step.scene_id for step in schedule_steps if step.status == "committed"
    }
    if committed_info_ids is None:
        committed_info_ids = set()
        for step in schedule_steps:
            if step.status == "committed":
                committed_info_ids.update(step.output_info_ids)

    unmet_info_ids = [
        info_id for info_id in coupling.required_info_ids if info_id not in committed_info_ids
    ]
    unmet_scene_ids = [
        scene_id
        for scene_id in coupling.required_scene_ids
        if scene_id not in committed_scene_ids
    ]
    unmet_event_ids = [
        event_id for event_id in coupling.input_event_ids if event_id not in committed_event_ids
    ]
    high_coupling = _is_high_coupling(coupling)
    has_unmet_requirement = bool(unmet_info_ids or unmet_scene_ids or unmet_event_ids)
    barrier_required = coupling.barrier_policy == "hard" or (
        high_coupling and has_unmet_requirement
    )
    blocked = high_coupling and has_unmet_requirement
    drift_minutes = _drift_minutes(coupling, run_mode, schedule_steps)

    if blocked:
        reason = "high coupling blocked by unmet requirements"
    elif barrier_required:
        reason = "hard barrier requirements satisfied"
    elif run_mode == "ktsl_full" and high_coupling:
        reason = "high coupling synchronized by KTSL coupling layer"
    elif has_unmet_requirement:
        reason = "low coupling may proceed independently"
    else:
        reason = "coupling requirements satisfied"

    return CouplingDecision(
        id=f"coupling_{run_mode}_{coupling.id}",
        run_mode=run_mode,
        coupling_id=coupling.id,
        status="blocked" if blocked else "allowed",
        condition_type=coupling.condition_type,
        coupling_score=coupling.coupling_score,
        barrier_required=barrier_required,
        barrier_id=coupling.barrier_id,
        required_info_ids=list(coupling.required_info_ids),
        required_scene_ids=list(coupling.required_scene_ids),
        input_event_ids=list(coupling.input_event_ids),
        output_info_ids=list(coupling.output_info_ids),
        unmet_required_info_ids=unmet_info_ids,
        unmet_required_scene_ids=unmet_scene_ids,
        unmet_input_event_ids=unmet_event_ids,
        drift_minutes=drift_minutes if high_coupling else 0,
        reason=reason,
    )


def _is_high_coupling(coupling: SceneCoupling) -> bool:
    return (
        coupling.coupling_score >= HIGH_COUPLING_THRESHOLD
        or coupling.mode in {"linked", "locked"}
        or coupling.barrier_policy == "hard"
    )


def _drift_minutes(
    coupling: SceneCoupling,
    run_mode: RunMode,
    schedule_steps: list[ScheduleStep],
) -> int:
    source_ends = [
        step.time_end_minute
        for step in schedule_steps
        if step.status == "committed" and step.scene_id == coupling.source_scene_id
    ]
    target_starts = [
        step.time_start_minute
        for step in schedule_steps
        if step.status == "committed" and step.scene_id == coupling.target_scene_id
    ]
    if not source_ends or not target_starts:
        drift_minutes = coupling.expected_drift_minutes
    else:
        drift_minutes = max(0, min(target_starts) - max(source_ends))
    if run_mode == "ktsl_full" and _is_high_coupling(coupling):
        return 0
    return drift_minutes


__all__ = ["HIGH_COUPLING_THRESHOLD", "evaluate_coupling", "evaluate_couplings"]
